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

`ask` and `n` belong to the turn they were written in: the next prompt is the
answer to them. `did` is the job the session is on, and the next prompt does
not change that, so the last one is kept beside the line until a newer one is
written.

Kept beside `seen.json` rather than in `config.json`: that file is yours to
hand-edit, and this one is rewritten by a hook every time a session stops.
"""
import codecs
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from pathlib import Path

# A line, not a paragraph. A model handed the field an essay would push every
# card below it off the screen, so the store is where the length is settled.
LIMIT = 160

# The id comes from a hook payload and it names a file. Claude Code writes
# uuids; anything that is not one has no business creating a path.
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


# What the hook writes is two clipped strings and a few numbers, under a kilobyte
# even when every character is escaped. A file bigger than this is not one of its
# lines, and nothing is read past it.
MAX_BYTES = 64 * 1024

# How long a read of one of these files may take. They are small and on the local
# disk; one that takes longer is behind a filesystem that has stopped answering (a
# network mount, or a link into one), where open, read and close each wait for it
# whatever flags they are given, and the poll holds the lock every poll takes.
READ_BUDGET = 0.5

# The reads still out, by path: at most one per file, so a file that never answers
# costs one thread and one wait, not a thread and a wait every poll.
_reading = {}
_reading_lock = threading.Lock()


class _Read:
    """One read of one file, on a thread of its own, and the moment it is given up on."""

    def __init__(self):
        self.done = threading.Event()
        self.data = None
        self.due = time.monotonic() + READ_BUDGET


def _run(key, read, path, limit):
    try:
        read.data = _plain_bytes(path, limit)
    except Exception:       # whatever it was, it is no line; a thread's traceback is nobody's
        read.data = None
    finally:
        with _reading_lock:
            _reading.pop(key, None)         # before the flag: a reader that sees it done finds no entry
        read.done.set()


def _small_bytes(path, limit):
    """The first `limit` bytes of a plain file, or None; None too when it does not answer in time.

    A reader that arrives while the read of the same file is out waits for that
    read, until its time is up, and not for a new one. Past that time the file is
    taken as not answering and every reader gets None at once until the read
    comes back; what a late read found is dropped, and the next call reads again.
    """
    key = str(path)
    with _reading_lock:
        read = _reading.get(key)
        if read is None:
            read = _reading[key] = _Read()
            try:
                threading.Thread(target=_run, args=(key, read, path, limit),
                                 name="lines-read", daemon=True).start()
            except RuntimeError:        # no thread to be had
                del _reading[key]
                return None
    if not read.done.wait(max(0.0, read.due - time.monotonic())):
        return None
    return read.data


def _plain_bytes(path, limit):
    """The first `limit` bytes of a plain file, or None. May wait on a filesystem that does not answer.

    The folder is anyone's to write in, and the poll that reads it holds the lock
    every poll takes: a pipe would be waited on for ever (and deleting it does not
    free the wait), a device or a link to one has no end, and a file of any size
    is read whole. So the file is opened without waiting and without taking it for
    a terminal, looked at once opened (the file, not the name: a link is followed
    and the thing it points to is judged), and only a regular file is read, and
    only up to the bound.
    """
    try:
        # O_NOCTTY: a process with no terminal that merely opens one is given it,
        # and is sent SIGHUP when it closes.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except (OSError, ValueError):       # ValueError: a NUL in the path
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read(limit)
    except OSError:
        return None
    finally:
        os.close(fd)


def read_plain(path, limit):
    """The first `limit` bytes of a plain file, or None. Waits for nothing: see `_plain_bytes`."""
    return _plain_bytes(path, limit)


def read_bounded(path, limit):
    """Like `read_plain`, and gives up (None) after `READ_BUDGET`: for a read made on every poll."""
    return _small_bytes(path, limit)


def write_atomic(path, text):
    """Put `text` in the file whole or not at all, and say whether it landed."""
    return _replace(path, text)


def store():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "agentview" / "lines"


def _file(session_id, root=None):
    if not isinstance(session_id, str) or not SAFE.fullmatch(session_id):
        return None
    return (Path(root) if root else store()) / f"{session_id}.json"


def _turn_file(session_id, root=None):
    path = _file(session_id, root)
    return None if path is None else path.with_suffix(".turn")


def _did_file(session_id, root=None):
    path = _file(session_id, root)
    return None if path is None else path.with_suffix(".did")


def current_turn(session_id, root=None):
    """Which turn this session is in, or `""` when nothing is tracking it."""
    path = _turn_file(session_id, root)
    if path is None:
        return ""
    # A turn id is 8 hex digits; 64 characters at most, 4 bytes each, is all there is to read.
    data = _small_bytes(path, 256)
    try:
        return "" if data is None else data.decode("utf-8").strip()[:64]
    except ValueError:
        return ""


def begin_turn(session_id, root=None):
    """A new turn: forget the last line and mint an identity for this one.

    The prompt that restarted a session is the answer to whatever it asked,
    so the line goes at the same moment. The last `did` stays (`kept_did`):
    it says what job the session is on, which a prompt does not end.

    The identity is what lets a line that outlives its turn be recognised --
    a moment in time could not, because a session can go idle, busy and idle
    again between two polls.
    """
    path = _turn_file(session_id, root)
    if path is None:
        return ""
    _seed_did(session_id, root)
    drop(session_id, root)
    turn = secrets.token_hex(4)
    return turn if _replace(path, turn) else ""


def fresh(session_id, root=None):
    """This session's line, but only if it belongs to the turn it is in."""
    got = read(session_id, root)
    if got and got["turn"] != current_turn(session_id, root):
        return {}
    return got


def kept_did(session_id, root=None):
    """The last `did` this session wrote, in whatever turn, or `""`.

    Never raises, like `read`.
    """
    path = _did_file(session_id, root)
    if path is None:
        return ""
    # Like the line and the turn, the did is read without waiting on what is at its
    # path: every poll reads it for every session, under the lock the page waits on.
    # Room for the blanks `_clip` squeezes out of a padded line, at four bytes a character.
    data = _small_bytes(path, 16 * LIMIT)
    if data is None:
        return ""
    try:
        # Not the final chunk: the bound may fall inside a character, which is no error.
        return _clip(codecs.getincrementaldecoder("utf-8")().decode(data))
    except ValueError:
        return ""


def read(session_id, root=None):
    """This session's line, or `{}` when it has not written one.

    Never raises. A hook killed mid-write leaves a half file behind, and the
    page not knowing what a session is up to is a smaller problem than the
    page not loading.
    """
    path = _file(session_id, root)
    if path is None:
        return {}
    data = _small_bytes(path, MAX_BYTES + 1)
    if data is None or len(data) > MAX_BYTES:
        return {}
    try:
        got = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        # RecursionError: a Python whose json stops at its recursion limit, on a
        # file of nothing but brackets. No hook writes one, a hand does, and
        # "never raises" is what keeps the page up.
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


def _replace(path, text):
    """Put `text` in the file whole or not at all, and say whether it landed."""
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(path)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except (OSError, ValueError):
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return False
    return True


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
    if not _replace(path, json.dumps(rec)):
        return None
    if rec["did"]:
        _keep_did(session_id, rec["did"], root)
    return rec


def _keep_did(session_id, did, root=None):
    """Remember a `did` past the turn it was written in.

    A line with none leaves the last one standing, and failing to keep one
    loses only that.
    """
    _replace(_did_file(session_id, root), did)


def _seed_did(session_id, root=None):
    """Keep the `did` of a line written before dids were kept, which has it
    in the line file alone and is about to lose that file."""
    if not kept_did(session_id, root):
        did = read(session_id, root).get("did")
        if did:
            _keep_did(session_id, did, root)


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
        found = (list(root.glob("*.json")) + list(root.glob("*.turn"))
                 + list(root.glob("*.did")))
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
