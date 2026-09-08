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
import secrets
import tempfile
import time
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


def _turn_file(session_id, root=None):
    path = _file(session_id, root)
    return None if path is None else path.with_suffix(".turn")


def current_turn(session_id, root=None):
    """Which turn this session is in, or `""` when nothing is tracking it."""
    path = _turn_file(session_id, root)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()[:64]
    except (OSError, ValueError):
        return ""


def begin_turn(session_id, root=None):
    """A new turn: forget the last line and mint an identity for this one.

    The prompt that restarted a session is the answer to whatever it asked,
    so the line goes at the same moment. The identity is what lets a line
    that outlives its turn be recognised -- a moment in time could not,
    because a session can go idle, busy and idle again between two polls.
    """
    path = _turn_file(session_id, root)
    if path is None:
        return ""
    drop(session_id, root)
    turn = secrets.token_hex(4)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(path)
        tmp.write_text(turn, encoding="utf-8")
        tmp.replace(path)
    except (OSError, ValueError):
        return ""
    return turn


def fresh(session_id, root=None):
    """This session's line, but only if it belongs to the turn it is in."""
    got = read(session_id, root)
    if got and got["turn"] != current_turn(session_id, root):
        return {}
    return got


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
    at = got.get("at") if isinstance(got.get("at"), (int, float)) else 0
    if not at:
        # `{}` parses and says nothing. Treating it as a line suppresses the
        # fallback and tells the hook the session already answered.
        return {}
    return {
        "did": _clip(got.get("did")),
        "ask": _clip(got.get("ask")),
        "n": _count(got.get("n")),
        "at": at,
        # Who put it there. A line read out of a transcript is a guess with
        # words in it; only a session speaking for itself is believed.
        "by": "session" if got.get("by") == "session" else "read",
        "turn": got.get("turn") if isinstance(got.get("turn"), str) else "",
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


def _tmp_for(path):
    """A temporary name of this write's own.

    One shared `<id>.json.tmp` is not atomic across writers: the second one
    truncates the first's file mid-write, and the loser reports success over
    a record that never landed.
    """
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + ".",
                                suffix=".tmp")
    os.close(fd)
    return Path(name)


def write(session_id, did="", ask="", n=0, root=None, at=None, by="session",
          turn=None):
    """Record what a session says about itself, atomically.

    Returns the record, or `None` when nothing was written. Failing open is
    right -- a dashboard that does not know is a small problem. Reporting a
    success that did not happen is not: `team-line` printed "line written"
    over a write that never landed.
    """
    path = _file(session_id, root)
    if path is None:
        return None
    # Stamped at the moment of writing, which is the whole proof: whatever
    # turn is current now is the turn this line belongs to.
    rec = {"did": _clip(did), "ask": _clip(ask), "n": _count(n),
           "at": at if at is not None else time.time(),
           "by": "session" if by == "session" else "read",
           "turn": current_turn(session_id, root) if turn is None else str(turn)}
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(path)
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        tmp.replace(path)
    except (OSError, ValueError):
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return None
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
        found = list(root.glob("*.json")) + list(root.glob("*.turn"))
    except OSError:
        return
    # A crashed write leaves `<id>.<random>.tmp` behind, whose stem is not a
    # session id and so never matched a live one -- it would sit forever.
    try:
        found += list(root.glob("*.tmp"))
    except OSError:
        pass
    for path in found:
        if path.suffix == ".tmp" or path.stem not in live:
            try:
                path.unlink()
            except OSError:
                pass
