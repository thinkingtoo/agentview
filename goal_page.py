"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, where it can be read and edited.

Only a hub that already runs is used. `sheaf status` says whether one does and
on which port. The path of the page (sheaf names a document by the root it
lies in, which only sheaf knows) is read from `sheaf list` when sheaf has
rendered the goal since the hub started: that renders nothing, so a title or a
theme the page was given stays. Only a goal it has not rendered is opened, with
`sheaf open FILE --no-browser`, once per goal per hub. `sheaf open` starts a
hub when none runs, so every round of opens follows a status asked just
before, in the same refresh, that said one does: the page and the poll never
start a hub. (A hub that stops in the moment between the two is started again
by that open; the window is one subprocess wide.)

sheaf takes a second or two to answer on a busy laptop, so the poll never
waits for it: `of` answers from what was learnt, and a stale answer is
refreshed by one thread of its own, the next poll showing what it found.
Without a hub the card gets the reason instead of a link, and sheaf is asked
again after `STATUS_EVERY` seconds.
"""
import os
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
# What `sheaf list` prints of a document: its page, and on the next line its file.
LISTED = re.compile(r"^\s*http://127\.0\.0\.1:\d{1,5}(/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]+)+\.md)[ \t]*\n"
                    r"[ \t]+(/.+?) \u00b7 ", re.MULTILINE)
NO_HUB = "no sheaf hub runs: start one with `sheaf start`"
NO_SHEAF = "sheaf is not installed"
MISSING = 127                   # the exit code of a command that is not there
ASKING = "asking sheaf for its hub"
NOT_OPENED = "sheaf could not open the goal file"

_LOCK = threading.Lock()
_hub = {"at": None, "port": None, "why": ""}
_paths = {}                     # (port, goal file) -> (the page's path on that hub or None, when asked)
_wanted = set()                 # the goal files the cards have asked for
_busy = [False]                 # a refresh is running


def forget():
    """Drop what was learnt of the hub, as at start."""
    with _LOCK:
        _hub.update(at=None, port=None, why="")
        _paths.clear()
        _wanted.clear()


def _run(args):
    """`(exit code, stdout)` of `sheaf ARGS`; a sheaf missing (`MISSING`) or too
    slow fails."""
    try:
        done = subprocess.run([SHEAF, *args], capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except OSError:
        return MISSING, ""
    except subprocess.SubprocessError:
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


def _status(now, run):
    code, out = run(["status"])
    found = RUNNING.search(out) if code == 0 else None
    with _LOCK:
        _hub.update(at=now, port=int(found.group(1)) if found else None,
                    why=NO_SHEAF if code == MISSING else NO_HUB)
    return _hub["port"]


def _listed(run):
    """{file: page path} of what the hub has rendered since it started."""
    code, out = run(["list"])
    return {} if code else {file: path for path, file in LISTED.findall(out)}


def _refresh(now, run):
    """Ask sheaf for its port, and then for the page of each goal not yet
    found on it. Runs outside the lock: sheaf is slow, and a card must not
    wait on it."""
    try:
        asked = _hub["at"] is None or now - _hub["at"] >= STATUS_EVERY
        port = _status(now, run) if asked else _hub["port"]
        with _LOCK:
            due = sorted(g for g in _wanted if port is not None and _due((port, g), now))
        if not due:
            return
        if not asked:                   # an open must follow a status of this very refresh
            port = _status(now, run)
            if port is None:
                return
        listed = _listed(run)
        for goal in due:
            path = listed.get(os.path.realpath(goal))
            if path is None:
                code, out = run(["open", goal, "--no-browser"])
                page = PAGE.search(out) if code == 0 else None
                path = page.group(1) if page else None
            with _LOCK:
                _paths[(port, goal)] = (path, now)
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
        try:
            start(lambda: _refresh(now, run))
        except RuntimeError:            # no thread to be had: the next poll tries again
            with _LOCK:
                _busy[0] = False
    with _LOCK:
        port = _hub["port"]
        if _hub["at"] is None:
            return {"url": None, "why": ASKING}
        if port is None:
            return {"url": None, "why": _hub["why"]}
        path, at = _paths.get((port, goal), (None, None))
    if at is None:
        return {"url": None, "why": ASKING}
    if path is None:
        return {"url": None, "why": NOT_OPENED}
    return {"url": f"http://127.0.0.1:{port}{path}", "why": ""}
