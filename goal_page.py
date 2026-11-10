"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, where it can be read and edited.

Only a hub that already runs is used. `sheaf status` says whether one does and
on which port; only then is `sheaf open FILE --no-browser` run, once per goal
per hub, for the path of the page (sheaf names a document by the root it lies
in, which only sheaf knows). `sheaf open` starts a hub when none runs, so it is
never run without a status that said one does: the page and the poll never
start a hub. (A hub that stops in the moment between the two is started again
by that open; the window is one subprocess wide, once per goal per hub.)

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

_LOCK = threading.Lock()
_hub = {"at": None, "port": None}
_paths = {}                     # (port, goal file) -> (the page's path on that hub or None, when asked)


def forget():
    """Drop what was learnt of the hub, as at start."""
    with _LOCK:
        _hub.update(at=None, port=None)
        _paths.clear()


def _run(args):
    try:
        done = subprocess.run([SHEAF, *args], capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 1, ""
    return done.returncode, done.stdout


def _port(now, run):
    if _hub["at"] is None or now - _hub["at"] >= STATUS_EVERY:
        try:
            code, out = run(["status"])
        except OSError:                 # no sheaf installed
            code, out = 1, ""
        found = RUNNING.search(out) if code == 0 else None
        _hub.update(at=now, port=int(found.group(1)) if found else None)
    return _hub["port"]


def of(track, now, run=_run):
    """`{"url", "why"}` for the card of `track`: the page of its goal file, or
    no URL and why not. None when the track has no goal file."""
    if not projects.TRACK_NAME.match(track):
        return None
    goal = projects.pm_dir() / f"{track}.goal.md"
    if not projects.regular(goal):
        return None
    with _LOCK:
        port = _port(now, run)
        if port is None:
            return {"url": None, "why": NO_HUB}
        key = (port, str(goal))
        path, at = _paths.get(key, (None, None))
        if at is None or (path is None and now - at >= STATUS_EVERY):      # a failure is asked again
            try:
                code, out = run(["open", str(goal), "--no-browser"])
            except OSError:
                code, out = 1, ""
            page = PAGE.search(out) if code == 0 else None
            path = page.group(1) if page else None
            _paths[key] = (path, now)
    if path is None:
        return {"url": None, "why": "sheaf could not open the goal file"}
    return {"url": f"http://127.0.0.1:{port}{path}", "why": ""}
