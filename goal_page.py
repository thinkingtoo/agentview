"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, where it can be read and edited.

Only a hub that already runs is used. `sheaf status` says whether one does and
on which port; only then is `sheaf open FILE --no-browser` run, once per goal
per hub, for the path of the page (sheaf names a document by the root it lies
in, which only sheaf knows). `sheaf open` starts a hub when none runs, so it is
never run without a status that said one does: the page and the poll never
start a hub. (A hub that stops in the moment between the two is started again
by that open; the window is one subprocess wide, once per goal per hub.)

sheaf takes a second or two to answer on a busy laptop, so the poll never
waits for it: `of` answers from what was learnt, and a stale answer is
refreshed by one thread of its own, the next poll showing what it found.
Without a hub the card gets the reason instead of a link, and sheaf is asked
again after `STATUS_EVERY` seconds.
"""
import re
import subprocess
import threading

import projects

SHEAF = "sheaf"
STATUS_EVERY = 30               # seconds between two looks at the hub
TIMEOUT = 10
RUNNING = re.compile(r"hub running on 127\.0\.0\.1:(\d{1,5})\b")
# The page `sheaf open` prints. sheaf percent-encodes every segment, so a path
# of anything else is no page of it.
PAGE = re.compile(r"http://127\.0\.0\.1:\d{1,5}(/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]+)+\.md)\s*$", re.MULTILINE)
NO_HUB = "no sheaf hub runs: start one with `sheaf start`"
ASKING = "asking sheaf for its hub"
NOT_OPENED = "sheaf could not open the goal file"

_LOCK = threading.Lock()
_hub = {"at": None, "port": None}
_paths = {}                     # (port, goal file) -> (the page's path on that hub or None, when asked)
_wanted = set()                 # the goal files the cards have asked for
_busy = [False]                 # a refresh is running


def forget():
    """Drop what was learnt of the hub, as at start."""
    with _LOCK:
        _hub.update(at=None, port=None)
        _paths.clear()
        _wanted.clear()


def _run(args):
    """`(exit code, stdout)` of `sheaf ARGS`; a sheaf missing or too slow fails."""
    try:
        done = subprocess.run([SHEAF, *args], capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout


def _due(key, now):
    """Whether the page of `key` is to be asked of sheaf: never asked, or asked
    and refused a while ago."""
    path, at = _paths.get(key, (None, None))
    return at is None or (path is None and now - at >= STATUS_EVERY)


def _stale(now):
    if _hub["at"] is None or now - _hub["at"] >= STATUS_EVERY:
        return True
    return _hub["port"] is not None and any(_due((_hub["port"], g), now) for g in _wanted)


def _refresh(now, run):
    """Ask sheaf for its port, and then for each goal not yet opened on it.
    Runs outside the lock: sheaf is slow, and a card must not wait on it."""
    try:
        if _hub["at"] is None or now - _hub["at"] >= STATUS_EVERY:
            code, out = run(["status"])
            found = RUNNING.search(out) if code == 0 else None
            with _LOCK:
                _hub.update(at=now, port=int(found.group(1)) if found else None)
        port = _hub["port"]
        if port is None:
            return
        with _LOCK:
            due = sorted(g for g in _wanted if _due((port, g), now))
        for goal in due:
            code, out = run(["open", goal, "--no-browser"])
            page = PAGE.search(out) if code == 0 else None
            with _LOCK:
                _paths[(port, goal)] = (page.group(1) if page else None, now)
    finally:
        with _LOCK:
            _busy[0] = False


def _start(work):
    threading.Thread(target=work, name="goal-page", daemon=True).start()


def of(track, now, run=_run, start=_start):
    """`{"url", "why"}` for the card of `track`: the page of its goal file, or
    no URL and why not. None when the track has no goal file. What is not known
    yet is asked of sheaf by `start`, never here."""
    if not projects.TRACK_NAME.match(track):
        return None
    goal = str(projects.pm_dir() / f"{track}.goal.md")
    if not projects.regular(goal):
        return None
    with _LOCK:
        _wanted.add(goal)
        go = _stale(now) and not _busy[0]
        if go:
            _busy[0] = True
    if go:
        start(lambda: _refresh(now, run))
    with _LOCK:
        port = _hub["port"]
        if _hub["at"] is None:
            return {"url": None, "why": ASKING}
        if port is None:
            return {"url": None, "why": NO_HUB}
        path, at = _paths.get((port, goal), (None, None))
    if at is None:
        return {"url": None, "why": ASKING}
    if path is None:
        return {"url": None, "why": NOT_OPENED}
    return {"url": f"http://127.0.0.1:{port}{path}", "why": ""}
