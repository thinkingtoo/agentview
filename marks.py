"""What you did with each session: one store, one lock, one file.

`marks.json` holds one record per `provider:id` key, a field absent when the
fact is:

    {key: {"seen": stop, "read": stop, "pinned": true}}

- **seen**: the stop you last looked at, `statusUpdatedAt`. A session that
  works again and stops again carries a new stop, so it is ready again with
  nothing to expire. Drives the chime and the `ready` flag.
- **read**: the stop whose handover you read in the overview (glossary:
  "Handover read"). Not the seen mark: old seen marks were also written by
  failed jumps, so they do not count as having read anything, and
  `fleet.look` can mark a session seen without reading it. Drives `unread`.
- **pinned**: held open as a full tile until unpinned or the session closes
  (glossary: "Pin (a session)").

Joining the storage does not join the facts. Kept out of `config.json`: that
file is yours to hand-edit, and this one changes every time you click.

Every writer is one read-modify-write under `_LOCK`, so a click and the
round (`poll.round`) cannot lose one another's write. The first `load` that
finds no `marks.json` builds it from the two files this store replaced,
`seen.json` and `finished.json`, which are never written or removed. Writes
never raise: not knowing what you have read is a smaller problem than a page
that will not load. A file that exists and cannot be read loads as empty and is
not rebuilt; the next mark, pin or forget moves it aside first, to
`marks.json.broken-<timestamp>`, and writes a fresh file.
"""
import json
import os
import threading
import time
from pathlib import Path

import log

DEFAULT_PROVIDER = "claude"

_LOCK = threading.RLock()
_unreadable = set()         # stores whose last read failed, so a skip logs once


def store():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "agentview" / "marks.json"


def _stamp(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clean(got):
    """Records as the file may hold them, minus anything that is not a fact."""
    out = {}
    for key, record in (got.items() if isinstance(got, dict) else ()):
        if not isinstance(key, str) or not isinstance(record, dict):
            continue
        kept = {field: record[field] for field in ("seen", "read") if _stamp(record.get(field))}
        if record.get("pinned") is True:
            kept["pinned"] = True
        if kept:
            out[key] = kept
    return out


_UNREADABLE = object()


def _json(path):
    """The parsed old file; None when it is not there or not JSON; `_UNREADABLE`
    when the read itself failed, which says nothing about the file."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except OSError:
        return _UNREADABLE
    except ValueError:
        return None


def _qualified(key):
    return key if ":" in key else f"{DEFAULT_PROVIDER}:{key}"


def _imported(path):
    """The records the two old files hold, beside `path`. A bare id gets the
    default provider; where it meets its own prefixed id, the later key in the
    file wins, as it did in `seen.migrate`. A file that is not there or is not
    JSON adds nothing; one whose read fails makes the import None, so the
    caller builds nothing this round and the import tries again."""
    out = {}

    def put(key, field, value):
        out.setdefault(_qualified(key), {})[field] = value

    seen = _json(path.with_name("seen.json"))
    finished = _json(path.with_name("finished.json"))
    if _UNREADABLE in (seen, finished):
        return None
    for key, stop in (seen.items() if isinstance(seen, dict) else ()):
        if isinstance(key, str) and _stamp(stop):
            put(key, "seen", stop)
    finished = finished if isinstance(finished, dict) else {}
    read, pinned = finished.get("read"), finished.get("pinned")
    for key, stop in (read.items() if isinstance(read, dict) else ()):
        if isinstance(key, str) and _stamp(stop):
            put(key, "read", stop)
    for key in (pinned if isinstance(pinned, list) else ()):
        if isinstance(key, str):
            put(key, "pinned", True)
    return out


def _read(path):
    """`(records, how)`: how is "ok", "missing", "broken" for a file that
    exists and is not a JSON object, is nested too deep, may not be read, or
    is a directory; or "error" when the read itself failed (too many open
    files, an I/O error): that says nothing about the file."""
    try:
        with path.open(encoding="utf-8") as fh:
            got = json.load(fh)
    except FileNotFoundError:
        return {}, "missing"
    except (ValueError, RecursionError, PermissionError, IsADirectoryError):
        return {}, "broken"
    except OSError:
        return {}, "error"
    _unreadable.discard(str(path))
    return _clean(got), ("ok" if isinstance(got, dict) else "broken")


def _build(path):
    """Under the lock: the records of `path`, building the file from the old
    files if it is not there. None when nothing could be settled this round: an
    old file or the file itself failed to read, or the file is broken."""
    got, how = _read(path)
    if how == "ok":
        return got
    if how != "missing":
        return None
    imported = _imported(path)
    return None if imported is None else _save(_clean(imported), path)


def load(path=None):
    """`{key: record}`. A file that exists and cannot be read is empty, and is
    not rebuilt from the old files; only a file that does not exist is, and
    only when the old files could be read (else it is empty until they can)."""
    path = Path(path or store())
    got, how = _read(path)
    if how != "missing":
        return got
    with _LOCK:
        # Another thread may have built it while this one waited.
        built = _build(path)
        return {} if built is None else built


def _skipped(path):
    """A writer left the store alone because a read failed. One line in the
    log when that starts; nothing more until a read works and fails again."""
    if str(path) not in _unreadable:
        _unreadable.add(str(path))
        log.event("marks_skipped", path=str(path),
                  why="a read of the marks or the files they are built from failed")


def _aside(path):
    """Move a file nobody can read out of the way of the next write, so the
    write does not destroy it. The new name, or None when it did not move."""
    stamp = time.strftime("%Y%m%dT%H%M%S")
    for n in range(100):
        target = path.with_name(f"{path.name}.broken-{stamp}" + (f"-{n}" if n else ""))
        if target.exists():
            continue
        try:
            path.replace(target)
            return target
        except OSError:
            return None
    return None


def _current(path):
    """The records a writer starts from, under the lock; None when the file is
    unreadable and could not be set aside, or when a read failed (then the
    writer leaves the file alone and, once, says so in the log)."""
    got, how = _read(path)
    if how == "error":
        _skipped(path)
        return None
    if how == "broken":
        target = _aside(path)
        if not target:
            return None
        # A fresh file at once: with none, the next load would rebuild from
        # the old files, and a forget that has nothing to drop writes nothing.
        # If even that cannot be written, put the old file back.
        if not _write({}, path):
            try:
                target.replace(path)
            except OSError:
                pass
            return None
        return {}
    if how == "missing":
        built = _build(path)
        if built is None:
            _skipped(path)
        return built
    return got


def _save(state, path):
    _write(state, path)
    return state


def _write(state, path):
    """True when the file was written."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(state, fh)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True


def ready(key, stamp, state):
    """Has this session stopped with something you have not looked at?"""
    if not stamp:
        return False
    return state.get(key, {}).get("seen") != stamp


def is_read(key, stamp, state):
    """Have you read the handover of this very stop?"""
    return bool(stamp) and state.get(key, {}).get("read") == stamp


def pinned(key, state):
    return bool(state.get(key, {}).get("pinned"))


def mark(key, stamp, read, path=None):
    """You looked at this session as it is at the stop `stamp` and, when
    `read`, read its handover: both in one write. `read` off leaves an
    existing read stop alone."""
    path = Path(path or store())
    if not key or not stamp:
        return
    with _LOCK:
        state = _current(path)
        if state is None:
            return
        record = state.setdefault(key, {})
        record["seen"] = stamp
        if read:
            record["read"] = stamp
        _save(state, path)


def pin(key, on, path=None):
    """Pin a session open as a full tile, or let it shrink again."""
    path = Path(path or store())
    if not key:
        return
    with _LOCK:
        state = _current(path)
        if state is None:
            return
        if on:
            state.setdefault(key, {})["pinned"] = True
        elif key in state:
            state[key].pop("pinned", None)
            if not state[key]:
                del state[key]
        _save(state, path)


def forget(drop, path=None):
    """Drop every record of the sessions in `drop` (and nothing else), so the
    file cannot grow forever and a pin ends with its session.

    Which sessions are gone is the round's decision (`poll.round`), and never
    those of a provider that missed the poll: forgetting its marks would bring
    everything you had already read back as `ready` when it returns. The file
    is read again under the lock, so a mark or a pin that landed since the
    round began survives. A key not here is nothing.
    """
    path = Path(path or store())
    with _LOCK:
        state = _current(path)
        if state is None:
            return {}
        kept = {key: record for key, record in state.items() if key not in drop}
        if len(kept) != len(state):
            _save(kept, path)
        return kept
