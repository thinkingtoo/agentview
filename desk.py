"""The merge desk, from a session's side: hand a pull request over, ask what became of it, take it back.

    desk ready OWNER/REPO N --what TEXT --rec merge|wait|dont [--why TEXT] [--after N] [--by NAME] [--ships TEXT]
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
import os
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
FLOOR = ".merge-desk.floor"
STATUS = ("ready", "pressing", "merged", "installed", "refused", "withdrawn")
PRESSED = STATUS[:-1]           # what `deskwatch.last_event` looks at: a withdrawal is not one
MAX_LOG = 2 * 1024 * 1024       # bytes: past this the log is rotated, so a poll never reads more


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


def _read_log():
    try:
        return log_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _size(p=None):
    try:
        return (p or log_path()).stat().st_size
    except FileNotFoundError:
        return 0


def _sieve(line):
    """The record a line of the log holds, or None when `history` skips the line."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get("event"), str) and isinstance(rec.get("key"), str) else None


def _floor_path():
    return log_path().with_name(FLOOR)


def _floor():
    """The size the log had just after it was last rotated, 0 when it never was or when the file holds nonsense:
    a log only grows after a rotation, so a floor above its size (or below nothing) is not one."""
    try:
        floor = int(_floor_path().read_text())
    except (OSError, ValueError):
        return 0
    return floor if 0 <= floor <= _size() else 0


def _due():
    """Whether the log is big enough to rotate: past MAX_LOG and past twice what it was after the last rotation."""
    size = _size()
    return size > MAX_LOG and size > 2 * _floor()


def _scan(fh):
    """Per key, the byte offset of its first record and of the ones a rotation may carry: the last (`any`), the
    last status record, the last press record, the last `ready`."""
    seen = {"first": {}, "any": {}, "status": {}, "pressed": {}, "ready": {}}
    at = 0
    for raw in iter(fh.readline, b""):
        rec = _sieve(raw.decode("utf-8", "replace"))
        if rec:
            k, event = rec["key"], rec["event"]
            seen["first"].setdefault(k, at)
            seen["any"][k] = at
            if event in STATUS:
                seen["status"][k] = (at, event)
            if event in PRESSED:
                seen["pressed"][k] = at
            if event == "ready":
                seen["ready"][k] = at
        at += len(raw)
    return seen


def _carry(seen, on_page):
    """({key: offsets to carry, in file order}, the offsets of the `ready` records carried whole)."""
    keep, whole = {}, set()
    for k in seen["first"]:
        at = {seen["any"][k]}
        if k in seen["status"]:
            at.add(seen["status"][k][0])
        if k in seen["pressed"]:
            at.add(seen["pressed"][k])
        if k in seen["ready"] and (k in on_page or seen["status"][k][1] in ("ready", "pressing")):
            at.add(seen["ready"][k])
            whole.add(seen["ready"][k])
        keep[k] = sorted(at)
    return keep, whole


def rotate():
    """Start a new log that holds what the desk still asks of the old one, and keep the old one beside it as
    `merge-desk.log.<time>`. Per key, in the order the keys first appeared: its last record, its last status
    record (the last record may be a `tidied`), its last press record (`last_event` skips a `withdrawn`), and
    its last `ready` whole while the key is on the page or its press is open, because the press compares what
    ships with that record and nothing else holds the raw lines. A `ready` carried only because it is the
    last press record loses its `ships`: a press that finds none says "hand it over again".
    Under the desk lock, so no record is written between the read and the replace; the new log is complete
    before it takes the old one's place, so a crash leaves one of the two. The new size is written to
    `.merge-desk.floor`: a log that is still big then is not rotated again until it has doubled, by any process.
    A rotation that cannot be made (no hard links, a full disk) leaves the log as it was."""
    with deskfile.locked():
        p = log_path()
        if not _due():
            return
        tmp = p.with_name(p.name + ".new")
        linked = None
        try:
            with open(p, "rb") as fh:
                seen = _scan(fh)
                keep, whole = _carry(seen, {i.key for i in deskfile.items()})
                ready_at = set(seen["ready"].values())
                with open(tmp, "wb") as out:
                    for k in sorted(seen["first"], key=seen["first"].get):
                        for at in keep[k]:
                            fh.seek(at)
                            raw = fh.readline()
                            if at not in whole and at in ready_at:
                                try:
                                    rec = json.loads(raw)
                                    rec.pop("ships", None)
                                    raw = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
                                except ValueError:
                                    pass                # a hand-edited line that does not round-trip: carried as it is
                            out.write(raw if raw.endswith(b"\n") else raw + b"\n")   # a cut last line must not swallow the next key's
                    out.flush()
                    os.fsync(out.fileno())
            stamp = time.strftime("%Y%m%dT%H%M%S")
            archive = p.with_name(f"{p.name}.{stamp}")
            n = 1
            while archive.exists():
                n += 1
                archive = p.with_name(f"{p.name}.{stamp}-{n}")
            os.link(p, archive)
            linked = archive
            os.replace(tmp, p)
        except (OSError, ValueError):
            for left in (tmp, linked):               # a rotation that did not happen leaves no archive, poll after poll
                try:
                    if left:
                        left.unlink(missing_ok=True)
                except OSError:
                    pass
            return
        try:                                          # the replace is done: nothing below may raise to the caller
            fd = os.open(p.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            _floor_path().write_text(str(_size()))
        except OSError:
            pass


def history(k=None):
    if _due():                  # before the lock: between MAX_LOG and twice the floor a poll takes none
        rotate()
    out = []
    for line in _read_log().split("\n"):   # not splitlines: U+2028 and \x85 inside a record would cut it
        rec = _sieve(line)
        if rec and (k is None or rec["key"] == k):
            out.append(rec)
    return out


def item_block(repo, n, what, rec, why, pinned, base, after, by, when, ships=None):
    """`ships`: the lines of "What ships" (deskships.read); with any, the item is a Deploy item."""
    rec_line = RECS[rec] + "." + (" " + why if why else "")
    lines_ = [f"- [ ] {'Deploy' if ships else 'Merge'} {key(repo, n)}: {what}",
              f"  - Recommendation: {rec_line}",
              f"  - Pinned commit: {pinned}" + (f", into {base}" if base else "")
              + (f"; must go after #{after}" if after else "")]
    if ships:
        lines_ += ["  - What ships:"] + ["    " + line for line in ships]
    lines_.append(f"  - Handed over by {by}, {when}.")
    return "\n".join(lines_) + "\n"


def gh(*args):
    """(exit code, output) of one `gh` call, for what `deskships` asks of GitHub."""
    if not GH:
        return 1, "gh was not found on PATH"
    try:
        got = subprocess.run([GH, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, ValueError, subprocess.TimeoutExpired) as err:
        return 1, str(err)
    return got.returncode, (got.stdout if got.returncode == 0 else got.stdout + got.stderr).strip()


def ready(repo, n, what, rec, why="", after=None, by="a session", ships=""):
    repo, n = check_repo(repo), check_number(n)
    if rec not in RECS:
        raise Refused(f"--rec is merge, wait or dont, not {rec!r}")
    what = flatten(what)
    if not what:
        raise Refused("--what says nothing")
    if after is not None:
        after = check_number(after)
        if after == n:
            raise Refused(f"--after {after} is the PR itself")
    state, head, base = pr_head(repo, n)
    if state != "OPEN":
        raise Refused(f"{key(repo, n)} is not open: GitHub says {state}")
    if not re.fullmatch(r"[0-9a-f]{40}", head or ""):
        raise Refused(f"GitHub gave no commit for {key(repo, n)}")
    import deskships                       # deskships uses flatten from here
    if not base:
        raise Refused(f"GitHub gave no base branch for {key(repo, n)}")
    try:
        shipped = deskships.read(repo, base, head, gh, outside=flatten(ships))
    except deskships.Unreadable as why_not:
        raise Refused(f"could not tell what merging {key(repo, n)} ships: {why_not}") from None
    block = item_block(repo, n, what, rec, flatten(why), head, flatten(base, 80), after,
                       flatten(by, 80) or "a session", time.strftime("%Y-%m-%d %H:%M"), shipped)
    with deskfile.locked():
        deskfile.put_item(key(repo, n), block)
        log("ready", key(repo, n), pinned=head, rec=rec, by=by, ships=shipped, base=base)   # raw: the press compares these, never the page
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
    last = next((r for r in reversed(history(k)) if r["event"] in STATUS), None)
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
    r.add_argument("--ships", default="", help="one line, for a repo whose main is run from outside GitHub: the item becomes a Deploy item")
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
            head = ready(a.repo, a.number, a.what, a.rec, a.why, a.after, a.by, a.ships)
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
