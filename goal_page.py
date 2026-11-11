"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, where it can be read and edited.

Only a hub that already runs is used, and nothing is ever rendered: `sheaf
status` says whether a hub runs and on which port, and the page's address is
worked out here from the roots sheaf keeps (`roots.json`, read and never
written), by sheaf's own rule (SPEC 8.2): the root of a file is the top of its
git work tree, else the deepest registered root that is no repository and
holds it. The hub serves any markdown file of a registered root at
`/<root>/<path>`, with the settings it kept for it. `sheaf open` is never run:
it starts a hub when none runs, restarts one of an older version, and records
a page's settings anew, wiping a title or theme it was given.

A goal whose root sheaf has not registered has no page yet; the card says so
and how to give it one. sheaf takes a second or two to answer on a busy
laptop, so the poll never waits for it: `of` answers from what was learnt, and
a stale answer is refreshed by one thread of its own, the next poll showing
what it found. Everything is asked again after `STATUS_EVERY` seconds.
"""
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote

import projects

SHEAF = "sheaf"
STATUS_EVERY = 30               # seconds between two looks at the hub
TIMEOUT = 10
RUNNING = re.compile(r"hub running on 127\.0\.0\.1:(\d{1,5})\b")
NONE_RUNS = "no hub is running"   # what `sheaf status` prints when nothing listens on its port
NO_HUB = "no sheaf hub runs: start one with `sheaf start`"
NO_SHEAF = "sheaf is not installed"
NO_ROOT = "sheaf has no root holding the goal file yet: open it once with `sheaf open FILE`"
UNREADABLE = "sheaf gave an answer agentview could not read"
SLOW = f"sheaf took more than {TIMEOUT} s to say whether its hub runs: asked again in {STATUS_EVERY} s"
UNSURE = f"sheaf could not tell whether its hub runs (a hub too busy to answer it): asked again in {STATUS_EVERY} s"
ASKING = "asking sheaf for its hub"
MISSING = 127                   # the exit code of a command that is not there
TIMED_OUT = 124                 # timeout(1)'s, for a sheaf that did not answer in TIMEOUT

_LOCK = threading.Lock()
_hub = {"at": None, "port": None, "why": ""}
_paths = {}                     # goal file -> the page's path on the hub, or None
_wanted = set()                 # the goal files the cards have asked for
_busy = [False]                 # a refresh is running


def roots_file():
    """sheaf's `roots.json`, where sheaf keeps it (its `paths.state_dir`)."""
    home = os.environ.get("SHEAF_HOME")
    if home:
        return Path(home).expanduser() / "state" / "roots.json"
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state and os.path.isabs(state) else Path.home() / ".local" / "state"
    return base / "sheaf" / "roots.json"


def forget():
    """Drop what was learnt of the hub, as at start."""
    with _LOCK:
        _hub.update(at=None, port=None, why="")
        _paths.clear()
        _wanted.clear()


def _run(args):
    """`(exit code, stdout)` of `sheaf ARGS`; a sheaf missing (`MISSING`), too
    slow (`TIMED_OUT`) or failing otherwise fails."""
    try:
        done = subprocess.run([SHEAF, *args], capture_output=True, text=True, errors="replace",
                              timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except OSError:
        return MISSING, ""
    except subprocess.TimeoutExpired:
        return TIMED_OUT, ""
    except subprocess.SubprocessError:
        return 1, ""
    return done.returncode, done.stdout


def _roots():
    """[(name, real path, is a git root)] of what sheaf has registered; [] when
    there is nothing to read or it is not what sheaf writes. A root whose path
    no file can have (a NUL in it) is left out, not the others with it."""
    try:
        with roots_file().open(encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(got, dict):
        return []
    roots = []
    for name, r in got.items():
        if isinstance(r, dict) and isinstance(r.get("path"), str) and os.path.isabs(r["path"]):
            try:
                roots.append((name, Path(os.path.realpath(r["path"])), r.get("git") is True))
            except ValueError:
                pass
    return roots


def _git_top(folder):
    for d in (folder, *folder.parents):
        if (d / ".git").exists():
            return d
    return None


def _address(goal, roots):
    """The page's path of `goal` on the hub, by sheaf's rule, or None when no
    registered root holds it (sheaf would register one on an open)."""
    real = Path(os.path.realpath(goal))
    top = _git_top(real.parent)
    if top is not None:
        root = next(((name, path) for name, path, _ in roots if path == top), None)
    else:
        inside = [(name, path) for name, path, git in roots if not git and path in real.parents]
        root = max(inside, key=lambda r: len(r[1].parts), default=None)
    if root is None:
        return None
    name, path = root
    return "/" + "/".join(quote(seg, safe="") for seg in (name, *real.relative_to(path).parts))


def _stale(now):
    return _hub["at"] is None or now - _hub["at"] >= STATUS_EVERY or any(g not in _paths for g in _wanted)


def _refresh(now, run):
    """Ask sheaf for its port, and read its roots for each goal's page. Runs
    outside the lock: sheaf is slow, and a card must not wait on it. A sheaf
    too slow to answer, or failing without saying no hub runs (its hub did
    not answer it), says nothing of the hub: the one found last is kept, for
    one look only, so a hub that died meanwhile is not linked for ever."""
    try:
        code, out = run(["status"])
        found = RUNNING.search(out) if code == 0 else None
        with _LOCK:
            wanted = sorted(_wanted)
            if found:
                port, why = int(found.group(1)), ""
            elif code == TIMED_OUT or (code == 1 and NONE_RUNS not in out):
                kept = _hub["why"] not in (SLOW, UNSURE)
                port, why = (_hub["port"] if kept else None), SLOW if code == TIMED_OUT else UNSURE
            else:
                port, why = None, NO_SHEAF if code == MISSING else NO_HUB
        roots = _roots() if port is not None else []
        paths = {goal: _address(goal, roots) for goal in wanted}
        with _LOCK:
            _hub.update(at=now, port=port, why=why)
            _paths.update(paths)
    except Exception:                   # whatever it was, the card says so and waits STATUS_EVERY
        with _LOCK:
            _hub.update(at=now, port=None, why=UNREADABLE)
            _paths.update((goal, None) for goal in _wanted)
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
        if _hub["at"] is None or goal not in _paths:
            return {"url": None, "why": ASKING}
        port, path = _hub["port"], _paths[goal]
        if port is None:
            return {"url": None, "why": _hub["why"]}
    if path is None:
        return {"url": None, "why": NO_ROOT}
    return {"url": f"http://127.0.0.1:{port}{path}", "why": ""}
