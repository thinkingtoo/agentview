"""What a session says about itself when it stops.

Claude Code writes a title and your last prompt, and neither answers the
question you actually have in front of thirteen cards: where is this, and
does it want something from me. Only the session knows that, so the session
writes it -- a Stop hook asks it for two fields as it finishes:

    did   where the work stands, in the language of the conversation
    ask   the one thing it is blocked on, verbatim
    n     how many things it is blocked on, 0 when it wants nothing

`ask` carries words only when `n` is 1. One blocked question is short enough
to answer from the page; four of them are a trip to the terminal, and quoting
the first of four would misrepresent the size of the job -- so the page
renders the count instead.

Kept beside `seen.json` rather than in `config.json`: that file is yours to
hand-edit, and this one is rewritten by a hook every time a session stops.
"""
import json
import os
import re
from pathlib import Path

# A line, not a paragraph. A model handed the field an essay would push every
# card below it off the screen, so the store is where the length is settled.
LIMIT = 160

# The id comes from a hook payload and it names a file. Claude Code writes
# uuids; anything that is not one has no business creating a path.
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def store():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "claude-team" / "lines"


def _file(session_id, root=None):
    if not isinstance(session_id, str) or not SAFE.fullmatch(session_id):
        return None
    return (Path(root) if root else store()) / f"{session_id}.json"


def read(session_id, root=None):
    """This session's line, or `{}` when it has not written one.

    Never raises. A hook killed mid-write leaves a half file behind, and the
    page not knowing what a session is up to is a smaller problem than the
    page not loading.
    """
    path = _file(session_id, root)
    if path is None:
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict):
        return {}
    return {
        "did": _clip(got.get("did")),
        "ask": _clip(got.get("ask")),
        "n": _count(got.get("n")),
        "at": got.get("at") if isinstance(got.get("at"), (int, float)) else 0,
    }


def _clip(value):
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value if len(value) <= LIMIT else value[:LIMIT - 1].rstrip() + "…"


def _count(value):
    # A model writing "four" here means four, but the page counts alarms with
    # it. Anything that is not a number is nothing wanted.
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def write(session_id, did="", ask="", n=0, root=None, at=None):
    """Record what a session says about itself, atomically."""
    import time
    path = _file(session_id, root)
    if path is None:
        return {}
    rec = {"did": _clip(did), "ask": _clip(ask), "n": _count(n),
           "at": at if at is not None else time.time()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        tmp.replace(path)
    except OSError:
        pass
    return rec


def drop(session_id, root=None):
    """Forget a line. A session going back to work has answered its own ask."""
    path = _file(session_id, root)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def forget(live, root=None):
    """Drop the lines of sessions that are gone, so the directory is bounded."""
    root = Path(root) if root else store()
    try:
        found = list(root.glob("*.json"))
    except OSError:
        return
    for path in found:
        if path.stem not in live:
            try:
                path.unlink()
            except OSError:
                pass
