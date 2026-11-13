"""The merge desk's watcher: a ticked Merge item is merged, at the commit that was reviewed, and nothing else.

`start()` runs `tick()` every few seconds on a thread of the server. A tick presses, one item at
a time in page order, every item that is ticked and has no result yet:

1. the PR's head must still be the item's pinned commit, else "the branch changed after the review";
2. while GitHub answers UNKNOWN it is asked again every 2 s, for up to 60 s;
3. anything but MERGEABLE is "GitHub says <state>";
4. `gh pr merge --merge --match-head-commit <pinned>`.

The result goes under the item (`deskfile.settle`); a refused press unticks the box. Every press is
two records in `merge-desk.log`: `pressing` before the first `gh` call, `merged` or `refused` after
the result is on the page. A press that has no result (the service was restarted under it) is
settled from GitHub at the next tick, before anything is pressed: merged there means `merged`
is recorded and nothing is pressed again; still open means `refused`, and the person presses again.

One at a time holds across processes: the whole tick is under a lock file that dies with its
holder. The desk file's own lock is never held across a `gh` call.

`gh` is the absolute path found once, in the system's own folders: no entry of the service's PATH
(`~/.local/bin` leads it) is consulted when a merge is made, and the child gets that PATH too.
"""
import contextlib
import datetime
import fcntl
import json
import os
import shutil
import subprocess
import threading
import time

import desk
import deskfile
import log

SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
GH = shutil.which("gh", path=SYSTEM_PATH)
POLL = 3            # seconds between ticks
WAIT_MAX = 60       # how long GitHub may answer UNKNOWN
WAIT_STEP = 2
POST_POLLS = 5
CANNOT = -1         # gh could not be run or timed out: what it did at GitHub is not known
CALL_TIMEOUT = 120
sleep = time.sleep
GRACE = 120         # seconds a press may still be completing at GitHub before a restart calls it not merged
LOCK = ".merge-desk.press.lock"
_warned = set()


class NotMerged(Exception):
    """The press is refused; the text says why and goes under the item."""


class TakenBack(NotMerged):
    """The person unticked or replaced the item while the press waited: nothing is written on the page."""


class Unsure(Exception):
    """GitHub could not be asked; the press stays open and is settled at a later tick."""


def gh(*args):
    """(exit code, output) of one `gh` call; (1, why) when it cannot be run."""
    if not GH or not os.path.isabs(GH):
        return 1, "gh was not found in " + SYSTEM_PATH.replace(":", ", ")
    try:
        got = subprocess.run([GH, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=CALL_TIMEOUT, env={**os.environ, "PATH": SYSTEM_PATH, "GH_PROMPT_DISABLED": "1"})
    except (OSError, subprocess.TimeoutExpired) as err:
        return CANNOT, str(err)
    return got.returncode, (got.stdout if got.returncode == 0 else got.stdout + got.stderr).strip()


def view(repo, n):
    """The PR as GitHub answers now: state, mergeable, headRefOid, mergeCommit."""
    code, out = gh("pr", "view", str(n), "-R", repo, "--json", "state,mergeable,headRefOid,mergeCommit")
    if code:
        raise Unsure(desk.flatten(out, 160))
    try:
        data = json.loads(out)
        ok = isinstance(data["state"], str) and isinstance(data["headRefOid"], str) \
            and isinstance(data.get("mergeable") or "", str)
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise Unsure("GitHub's answer could not be read")
    return data


def merge_sha(pr):
    commit = pr.get("mergeCommit")
    return (commit.get("oid") or "") if isinstance(commit, dict) else ""


def record(event, k, **fields):
    with deskfile.locked():
        desk.log(event, k, **fields)


def last_event(k):
    return next((r for r in reversed(desk.history(k))
                 if r["event"] in ("ready", "pressing", "merged", "refused")), None)


def split(k):
    repo, _, n = k.rpartition("#")
    return repo, n


def finish(k, pinned, event, text, untick=False, **fields):
    """Page and log together, under the desk lock. An item handed over again since the press began
    is not written on, and a refusal that was never about it is not logged over its `ready`."""
    with deskfile.locked():
        cur = item(k)
        same = bool(cur) and cur.pinned == pinned
        page = fields.pop("page", True)
        if same and page:
            deskfile.edit(lambda t: deskfile.settle(t, k, desk.flatten(text), untick, pinned))
        last = last_event(k)
        if event == "merged" or not (last and last["event"] == "ready"):   # a newer hand-over already closed this press
            desk.log(event, k, **fields)


def merged_text(sha, already=False):
    when = time.strftime("%H:%M")
    return (f"Already merged as {sha[:7]}" if already and sha else "Already merged" if already
            else f"Merged as {sha[:7]}" if sha else "Merged") + f" at {when}"


@contextlib.contextmanager
def press_lock():
    path = deskfile.path().parent / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


def item(k):
    return next((i for i in deskfile.items() if i.key == k), None)


def check_and_merge(k, pinned):
    """Make the merge or raise NotMerged. Returns (sha, already_merged)."""
    repo, n = split(k)
    pr = None
    for waited in range(WAIT_MAX // WAIT_STEP + 1):
        try:
            pr = view(repo, n)
        except Unsure as why:                               # nothing was pressed yet: refuse, the person presses again
            raise NotMerged(f"GitHub could not be asked: {why}") from None
        if pr["state"] == "MERGED":
            if pr["headRefOid"] != pinned:
                raise NotMerged(f"the PR is already merged, but at {pr['headRefOid'][:7]}, not the reviewed {pinned[:7]}")
            return merge_sha(pr), True
        if pr["state"] != "OPEN":
            raise NotMerged(f"the PR is {pr['state'].lower()}, not open")
        if pr["headRefOid"] != pinned:
            raise NotMerged(f"the branch changed after the review (reviewed {pinned[:7]}, now {pr['headRefOid'][:7]})")
        if pr.get("mergeable") != "UNKNOWN":
            break
        if waited < WAIT_MAX // WAIT_STEP:
            sleep(WAIT_STEP)
    if pr.get("mergeable") == "UNKNOWN":
        raise NotMerged(f"GitHub still says UNKNOWN after {WAIT_MAX} s")
    if pr.get("mergeable") != "MERGEABLE":
        raise NotMerged(f"GitHub says {pr.get('mergeable')}")
    now = item(k)                                           # the person may have taken the press back while we waited
    if not now or not now.ticked or now.pinned != pinned:
        raise TakenBack("the press was taken back before the merge")
    code, out = gh("pr", "merge", str(n), "-R", repo, "--merge", "--match-head-commit", pinned)
    after = view(repo, n)                                   # an unreadable answer leaves the press open
    for _ in range(POST_POLLS if code == 0 else 0):         # accepted, but GitHub may still show it open for a moment
        if after["state"] != "OPEN":
            break
        sleep(WAIT_STEP)
        after = view(repo, n)
    if code == 0 and after["state"] == "OPEN":
        raise Unsure("the merge was accepted but GitHub still shows the PR open")
    if code == CANNOT and after["state"] == "OPEN":
        raise Unsure(f"the merge call did not finish: {desk.flatten(out, 120)}")
    if after["state"] == "MERGED":
        if after["headRefOid"] != pinned:
            raise NotMerged(f"the PR is merged, but at {after['headRefOid'][:7]}, not the reviewed {pinned[:7]}")
        return merge_sha(after), False
    raise NotMerged("the merge failed: " + desk.flatten(out or f"gh exited {code}", 200))


def press(k):
    with deskfile.locked():
        it = item(k)
        last = last_event(k)
        if not it or not it.ticked or (last and last["event"] in ("pressing", "merged")):
            return
        pinned = it.pinned
        desk.log("pressing", k, pinned=pinned)
    try:
        if not pinned:
            raise NotMerged("the item names no pinned commit")
        sha, already = check_and_merge(k, pinned)
    except TakenBack as why:
        finish(k, pinned, "refused", "", False, why=str(why), page=False)
    except NotMerged as why:
        finish(k, pinned, "refused", f"Not merged: {why}", True, why=str(why))
    except Unsure as why:
        log.error("desk-press", why, key=k)
        with deskfile.locked():                                 # the grace before recovery calls it unmerged starts now,
            last = last_event(k)                                # unless a newer hand-over already closed this press
            if last and last["event"] == "pressing" and last.get("pinned") == pinned:
                desk.log("pressing", k, pinned=pinned, again=True)
    else:
        finish(k, pinned, "merged", merged_text(sha, already), sha=sha, already=already)


def age(rec):
    try:
        return time.time() - datetime.datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (KeyError, ValueError, TypeError):
        return float("inf")


def recover():
    """Settle each press that began and never recorded a result. Never presses."""
    last = {}
    for rec in desk.history():
        if rec["event"] in ("ready", "pressing", "merged", "refused", "withdrawn"):
            last[rec["key"]] = rec
    for k, rec in last.items():
        if rec["event"] != "pressing":
            continue
        repo, n = split(k)
        try:
            pr = view(repo, n)
        except Unsure:
            continue
        pinned = rec.get("pinned", "")
        if pr["state"] == "MERGED" and pr["headRefOid"] == pinned:
            sha = merge_sha(pr)
            finish(k, pinned, "merged", merged_text(sha, already=True), sha=sha, recovered=True)
        elif pr["state"] == "MERGED":
            why = f"the PR was merged, but at {pr['headRefOid'][:7]}, not the reviewed {pinned[:7]}"
            finish(k, pinned, "refused", f"Not merged: {why}", True, why=why, recovered=True)
        elif age(rec) >= GRACE:             # a merge that reached GitHub before the crash may still be completing
            why = "the press was interrupted before it finished; GitHub shows the PR not merged"
            finish(k, pinned, "refused", f"Not merged: {why}", True, why=why, recovered=True)


def tick():
    with press_lock() as got:
        if not got:
            return
        recover()
        every = [i.key for i in deskfile.items()]
        for k in dict.fromkeys(i.key for i in deskfile.items() if i.ticked and not i.key.startswith("install:")):
            if every.count(k) > 1:                              # which of two is meant? press neither
                if k not in _warned:
                    _warned.add(k)
                    log.error("desk-press", ValueError("two items with one key"), key=k)
                continue
            press(k)


def run():
    while True:
        try:
            tick()
        except Exception as exc:        # a watcher that dies leaves ticked boxes unanswered
            log.error("desk-watch", exc)
        time.sleep(POLL)


def start():
    threading.Thread(target=run, name="desk-watch", daemon=True).start()
