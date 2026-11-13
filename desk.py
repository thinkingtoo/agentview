"""The merge desk, from a session's side: hand a pull request over, ask what became of it, take it back.

    desk ready OWNER/REPO N --what TEXT --rec merge|wait|dont [--why TEXT] [--after N] [--by NAME]
    desk status [OWNER/REPO N]
    desk withdraw OWNER/REPO N
    desk page [--no-browser]

`ready` pins the PR's head as it is now and puts one item on the desk page
(`deskfile`); handing the same PR over again replaces the item and re-pins. It
refuses a PR that is not open. Every change is also one line in `merge-desk.log`,
beside the page, which is what `status` reads: the watcher that merges ticked
items writes `merged` and `refused` lines there.

The state lives under `$XDG_STATE_HOME/agentview/`, never under `~/.claude`.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time

import deskfile
import lines

# Resolved once, when the command starts: under a service PATH is not the shell's.
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"   # the system's own folders: where the watcher looks for what it runs
GH = shutil.which("gh")
SHEAF = shutil.which("sheaf")

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
RECS = {"merge": "merge", "wait": "wait", "dont": "don't merge"}
TEXT_MAX = 300
LOG = "merge-desk.log"


class Refused(Exception):
    """Nothing was changed. The text says why."""


def flatten(text, limit=TEXT_MAX):
    """One line that cannot make a second task line or open a comment: line breaks
    become spaces, a leading list marker or box is dropped, comment marks are broken."""
    one = " ".join(str(text).split())
    one = re.sub(r"^(?:[-*+>#]\s*|\[[ xX]?\]\s*)+", "", one)
    one = re.sub(r"\[([ xX]?)\]", r"(\1)", one)           # no box anywhere in the line
    one = one.replace("<!--", "< !--").replace("-->", "-- >")
    return one if len(one) <= limit else one[:limit - 1].rstrip() + "…"


def check_repo(repo):
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or any(part in (".", "..") for part in repo.split("/")) or repo[0] in ".-"):
        raise Refused(f"{repo!r} is not owner/name")
    return repo


def check_number(n):
    if not str(n).isdigit() or int(n) < 1:
        raise Refused(f"{n!r} is not a PR number")
    return int(n)


def pr_head(repo, n):
    """(state, head sha) of the PR, read from GitHub through `gh`."""
    if not GH:
        raise Refused("gh was not found on PATH")
    try:
        got = subprocess.run([GH, "pr", "view", str(n), "-R", repo, "--json", "state,headRefOid,baseRefName"],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Refused(f"could not ask GitHub about {repo}#{n}: {err}") from None
    if got.returncode != 0:
        raise Refused(f"GitHub has no {repo}#{n}, or could not be asked: {flatten(got.stderr or got.stdout, 160)}")
    try:
        data = json.loads(got.stdout)
        return data["state"], data["headRefOid"], data.get("baseRefName", "")
    except (ValueError, KeyError, TypeError):
        raise Refused(f"GitHub's answer about {repo}#{n} could not be read") from None


def key(repo, n):
    return f"{repo}#{n}"


def log_path():
    return deskfile.path().parent / LOG


def log(event, k, **fields):
    """One line per press, hand-over and result. Callers hold the desk lock."""
    line = json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, "key": k, **fields},
                      ensure_ascii=False)
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def history(k=None):
    try:
        raw = log_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in raw:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if (isinstance(rec, dict) and isinstance(rec.get("event"), str) and isinstance(rec.get("key"), str)
                and (k is None or rec["key"] == k)):
            out.append(rec)
    return out


def item_block(repo, n, what, rec, why, pinned, base, after, by, when):
    rec_line = RECS[rec] + "." + (" " + why if why else "")
    lines_ = [f"- [ ] Merge {key(repo, n)}: {what}",
              f"  - Recommendation: {rec_line}",
              f"  - Pinned commit: {pinned}" + (f", into {base}" if base else "")
              + (f"; must go after #{after}" if after else ""),
              f"  - Handed over by {by}, {when}."]
    return "\n".join(lines_) + "\n"


def ready(repo, n, what, rec, why="", after=None, by="a session"):
    repo, n = check_repo(repo), check_number(n)
    if rec not in RECS:
        raise Refused(f"--rec is merge, wait or dont, not {rec!r}")
    what = flatten(what)
    if not what:
        raise Refused("--what says nothing")
    if after is not None:
        after = check_number(after)
    state, head, base = pr_head(repo, n)
    if state != "OPEN":
        raise Refused(f"{key(repo, n)} is not open: GitHub says {state}")
    if not re.fullmatch(r"[0-9a-f]{40}", head or ""):
        raise Refused(f"GitHub gave no commit for {key(repo, n)}")
    block = item_block(repo, n, what, rec, flatten(why), head, flatten(base, 80), after,
                       flatten(by, 80) or "a session", time.strftime("%Y-%m-%d %H:%M"))
    with deskfile.locked():
        deskfile.put_item(key(repo, n), block)
        log("ready", key(repo, n), pinned=head, rec=rec, by=by)
    return head


def withdraw(repo, n):
    repo, n = check_repo(repo), check_number(n)
    with deskfile.locked():
        present = any(i.key == key(repo, n) for i in deskfile.items())
        if present:
            deskfile.drop_item(key(repo, n))
            log("withdrawn", key(repo, n))
    return present


def status_line(k):
    last = next((r for r in reversed(history(k)) if r["event"] in ("ready", "withdrawn", "pressing", "merged", "installed", "refused")), None)
    if last is None:
        return f"{k}: not on the desk"
    ev = last["event"]
    if ev == "ready":
        pinned = last.get("pinned", "")[:7]
        return f"{k}: waiting (pinned {pinned}, handed over {last.get('at', '?')})"
    if ev == "pressing":
        return f"{k}: being merged now"
    if ev == "merged":
        return f"{k}: merged as {str(last.get('sha', ''))[:7]} at {last.get('at', '?')}"
    if ev == "installed":
        return f"{k}: installed as {str(last.get('sha', ''))[:7]} at {last.get('at', '?')}"
    if ev == "refused":
        return f"{k}: refused: {last.get('why', 'no reason given')}"
    return f"{k}: withdrawn at {last.get('at', '?')}"


def status_all():
    keys = []
    for r in history():
        if r["key"] not in keys:
            keys.append(r["key"])
    return [status_line(k) for k in keys] or ["the desk has no history"]


def page(browser=True):
    if not SHEAF:
        raise Refused("sheaf was not found on PATH")
    f = deskfile.path()
    with deskfile.locked():
        if not f.exists():
            if not lines.write_atomic(f, deskfile.SKELETON):
                raise Refused(f"could not write {f}")
    cmd = [SHEAF, "open", str(f)] + ([] if browser else ["--no-browser"])
    try:
        got = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Refused(f"sheaf open failed: {err}") from None
    if got.returncode != 0:
        raise Refused(f"sheaf open failed: {flatten(got.stderr or got.stdout, 200)}")
    return got.stdout.strip()


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    p = argparse.ArgumentParser(prog="desk", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ready", help="hand a PR over: pin its head, put it on the desk page")
    r.add_argument("repo")
    r.add_argument("number")
    r.add_argument("--what", required=True, help="one line on what the PR does")
    r.add_argument("--rec", required=True, help="merge, wait or dont")
    r.add_argument("--why", default="", help="the evidence: reviews, CI")
    r.add_argument("--after", help="a PR number that must be merged first")
    r.add_argument("--by", default="a session", help="who hands it over")
    s = sub.add_parser("status", help="waiting, merged as <sha>, or refused and why")
    s.add_argument("repo", nargs="?")
    s.add_argument("number", nargs="?")
    w = sub.add_parser("withdraw", help="take a PR off the desk")
    w.add_argument("repo")
    w.add_argument("number")
    g = sub.add_parser("page", help="open the desk page in sheaf; prints its address")
    g.add_argument("--no-browser", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "ready":
            head = ready(a.repo, a.number, a.what, a.rec, a.why, a.after, a.by)
            print(f"{key(a.repo, a.number)} is on the desk, pinned at {head}", file=out)
        elif a.cmd == "withdraw":
            if not withdraw(a.repo, a.number):
                raise Refused(f"{key(a.repo, a.number)} is not on the desk")
            print(f"{key(a.repo, a.number)} is off the desk", file=out)
        elif a.cmd == "status":
            if (a.repo is None) != (a.number is None):
                raise Refused("give both OWNER/REPO and N, or neither")
            for line in ([status_line(key(check_repo(a.repo), check_number(a.number)))] if a.repo else status_all()):
                print(line, file=out)
        else:
            print(page(browser=not a.no_browser), file=out)
    except (Refused, OSError) as why:
        print(f"desk: {why}", file=err)
        return 1
    return 0
