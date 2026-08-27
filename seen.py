"""Which sessions you have already looked at since they stopped.

A finished session is *ready* until you look at it. That needs one fact per
session, and the fact has a subtlety worth stating: what is remembered is not
"you saw this session" but **when it stopped**, `statusUpdatedAt`. A session
that works again and stops again carries a new one, so it becomes ready by
itself. Nothing has to expire, nothing has to be cleared, and there is no
state that can quietly go stale.

Kept out of `config.json` on purpose: that file is yours to hand-edit, and
this one changes every time you click.
"""
import json
import os
from pathlib import Path


def store():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "claude-team" / "seen.json"


def load(path=None):
    try:
        with (path or store()).open(encoding="utf-8") as fh:
            got = json.load(fh)
        return {k: v for k, v in got.items() if isinstance(v, (int, float))}
    except (OSError, ValueError, AttributeError):
        return {}


def save(marks, path=None):
    """Write the marks, atomically, keeping only sessions still on disk.

    Never raises: not knowing what you have read is a smaller problem than a
    page that will not load.
    """
    path = path or store()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(marks, fh)
        tmp.replace(path)
    except OSError:
        pass
    return marks


def mark(session_id, stamp, path=None):
    """Note that you have seen this session as it is now."""
    if not session_id or not stamp:
        return load(path)
    marks = load(path)
    marks[session_id] = stamp
    return save(marks, path)


def ready(session_id, stamp, marks):
    """Has this session stopped with something you have not looked at?"""
    if not stamp:
        return False
    return marks.get(session_id) != stamp


def forget(live, path=None):
    """Drop sessions that no longer exist, so the file cannot grow forever."""
    marks = load(path)
    kept = {sid: at for sid, at in marks.items() if sid in live}
    if len(kept) != len(marks):
        save(kept, path)
    return kept
