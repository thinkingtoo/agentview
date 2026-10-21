#!/usr/bin/env python3
# vendored from claude-boss@430098a -- do not edit, run scripts/vendor-ci-state
"""Is a branch's work waiting on CI, and until when.

    ci_state(repo, branch) -> {status, conclusion, queued_for_s, running_for_s,
                               eta_s, eta_excludes_queue, run_url, head_sha, error}

`head_sha` is the commit the run is for, so a caller can tell a run of its own
HEAD from one somebody else pushed to the same branch. `status` is GitHub's own for the branch's latest Actions run: queued,
in_progress or completed, or `unknown` when nothing usable is known. It is a
fact, read from `gh api repos/<owner>/<name>/actions/runs`. `eta_s` is an
estimate: the median duration of that workflow's last successful runs, minus
the time the run has already been going. A queued run's ETA leaves the queue
out (`eta_excludes_queue`): the token cannot see the queue position, which
needs the org runners API with admin scope.

The caller never waits on the network. `ci_state` reads a cache file and, when
it is missing or older than MAX_AGE_S, starts `ci_state.py refresh` as a
detached process; the next read sees its answer. A failed refresh keeps the
last good answer until it is STALE_S old, then reads as `unknown`. Every
failure is a value, never an exception: agentview calls this on its poll path,
where a read that hangs freezes every tile.

`repo` is `owner/name` (github.com) or `host/owner/name` (what agentview's
projects.py gives); a host other than github.com is asked with `gh --hostname`.
GitHub's waiting statuses (waiting, pending, requested) read as `queued`. The cache lives in $CI_STATE_CACHE, default ~/.cache/ci-state.

The master copy lives in claude-boss (skills/boss/ci_state.py). A vendored copy
carries a "vendored from" line under the shebang; change the master, not it.

CLI:
    ci_state.py get <repo> <branch>        the state as JSON
    ci_state.py refresh <repo> <branch>    fetch now (what `get` starts detached)
"""
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_S = 60          # a cached answer older than this is fetched again
STALE_S = 900           # a cached answer older than this is no answer
REFRESH_S = 30          # one refresh's budget; a lock older than this is dead
GH_TIMEOUT_S = 15
HISTORY = 10            # successful runs the ETA's median is taken over
# GitHub's run statuses that wait for a runner, an approval or a concurrency slot.
WAITING = {"queued", "waiting", "pending", "requested"}
STATUSES = WAITING | {"in_progress", "completed"}


def cache_dir():
    return Path(os.environ.get("CI_STATE_CACHE") or Path.home() / ".cache" / "ci-state")


def host_repo(repo):
    """(host, owner/name). `owner/name` is on github.com; any other host is its own repo."""
    parts = repo.strip("/").split("/")
    host = parts[-3] if len(parts) >= 3 else "github.com"
    return host, "/".join(parts[-2:])


def cache_file(repo, branch):
    key = hashlib.sha1(("%s/%s\0%s" % (host_repo(repo) + (branch,))).encode()).hexdigest()[:16]
    return cache_dir() / ("%s.json" % key)


def ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def unknown(error=None):
    return {"status": "unknown", "conclusion": None, "queued_for_s": None,
            "running_for_s": None, "eta_s": None, "eta_excludes_queue": False,
            "run_url": None, "head_sha": None, "error": error}


def start_refresh(repo, branch):
    """Start one detached refresh unless one is already running."""
    lock = cache_file(repo, branch).with_suffix(".lock")
    attempt = cache_file(repo, branch).with_suffix(".attempt")
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        try:
            # A refresh that failed fast leaves no newer cache: without this,
            # every poll would start another one.
            if 0 <= time.time() - attempt.stat().st_mtime < MAX_AGE_S:
                return
        except FileNotFoundError:
            pass
        try:
            if 0 <= time.time() - lock.stat().st_mtime < REFRESH_S:
                return
            lock.unlink()
        except FileNotFoundError:
            pass
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "refresh", repo, branch],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def ci_state(repo, branch, now=None):
    now = now or time.time()
    f = cache_file(repo, branch)
    try:
        age = now - f.stat().st_mtime
        cached = json.loads(f.read_text(encoding="utf-8"))
    except Exception:                     # any file, any shape: never raise here
        age, cached = None, None
    if age is not None and age < 0:
        age = MAX_AGE_S + 1               # written "in the future": the clock stepped back
    if age is None or age > MAX_AGE_S:
        start_refresh(repo, branch)
    if cached is None or age > STALE_S:
        return unknown()
    try:
        return from_cache(cached, now)
    except Exception:                     # the contract: never raise on the caller's path
        return unknown("malformed cache")


def from_cache(cached, now):
    """The state a cached refresh says, at `now`. Anything not of the shape
    `refresh` writes reads as unknown: a file from another version or a torn
    write must not raise on the caller's poll path."""
    if not isinstance(cached, dict):
        return unknown("malformed cache")
    run = cached.get("run")
    if not run:
        return unknown(cached.get("error") if isinstance(cached.get("error"), str) else None)
    if not isinstance(run, dict) or run.get("status") not in STATUSES:
        return unknown("malformed cache")
    out = unknown()
    status = run["status"]
    out.update(status="queued" if status in WAITING else status, conclusion=run.get("conclusion"),
               run_url=run.get("html_url"),
               head_sha=run.get("head_sha") if isinstance(run.get("head_sha"), str) else None)
    median = cached.get("median_s")
    if isinstance(median, bool) or not isinstance(median, (int, float)) \
            or not math.isfinite(median) or median <= 0:
        median = None
    started = ts(run.get("run_started_at"))
    if out["status"] == "queued":
        # run_started_at is the current attempt's start (it resets on a re-run;
        # created_at keeps the first attempt's). A `waiting` run may have entered
        # that state after earlier jobs ran: no timestamp says when, so no wait.
        since = started or ts(run.get("created_at"))
        if status != "waiting" and since:
            out["queued_for_s"] = max(0, int(now - since))
        out["eta_s"] = int(median) if median else None
        out["eta_excludes_queue"] = True
    elif out["status"] == "in_progress" and started:
        out["running_for_s"] = max(0, int(now - started))
        out["eta_s"] = max(0, int(median - out["running_for_s"])) if median else None
    return out


def gh(host, path):
    cmd = ["gh", "api"] + (["--hostname", host] if host != "github.com" else []) + [path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200] or "gh exit %d" % r.returncode)
    return json.loads(r.stdout)


def refresh(repo, branch):
    f = cache_file(repo, branch)
    lock = f.with_suffix(".lock")
    errors = (RuntimeError, subprocess.SubprocessError, OSError, ValueError, AttributeError)
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        f.with_suffix(".attempt").touch()
    except OSError:
        pass
    try:
        host, on = host_repo(repo)
        runs = gh(host, "repos/%s/actions/runs?branch=%s&per_page=1"
                  % (on, urllib.parse.quote(branch, safe=""))).get("workflow_runs") or []
        run = runs[0] if runs else None
        median = None
        if run and run.get("workflow_id"):
            # The ETA is optional: a failed history read keeps the run's status.
            try:
                hist = gh(host, "repos/%s/actions/workflows/%s/runs?status=success&per_page=%d"
                          % (on, run["workflow_id"], HISTORY)).get("workflow_runs") or []
                spans = [ts(h.get("updated_at")) - ts(h.get("run_started_at")) for h in hist
                         if ts(h.get("updated_at")) and ts(h.get("run_started_at"))]
                spans = [x for x in spans if x > 0]
                median = statistics.median(spans) if spans else None
            except errors:
                median = None
        body = {"run": run, "median_s": median}
    except errors as e:
        if f.exists():
            return 1                      # keep the last good answer; it ages to stale
        body = {"run": None, "median_s": None, "error": str(e)[:200]}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text(json.dumps(body), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        return 1
    return 0


def main(argv):
    if len(argv) == 3 and argv[0] in ("get", "refresh"):
        if argv[0] == "refresh":
            return refresh(argv[1], argv[2])
        print(json.dumps(ci_state(argv[1], argv[2])))
        return 0
    print("usage: ci_state.py get|refresh <repo> <branch>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
