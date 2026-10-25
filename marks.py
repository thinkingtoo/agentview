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
that will not load.
"""
import json
import os
import threading
from pathlib import Path

DEFAULT_PROVIDER = "claude"

_LOCK = threading.RLock()


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


def _json(path):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _qualified(key):
    return key if ":" in key else f"{DEFAULT_PROVIDER}:{key}"


def _imported(path):
    """The records the two old files hold, beside `path`. A bare id gets the
    default provider; where it meets its own prefixed id, the later key in the
    file wins, as it did in `seen.migrate`. A file that cannot be read adds
    nothing."""
    out = {}

    def put(key, field, value):
        out.setdefault(_qualified(key), {})[field] = value

    seen = _json(path.with_name("seen.json"))
    for key, stop in (seen.items() if isinstance(seen, dict) else ()):
        if isinstance(key, str) and _stamp(stop):
            put(key, "seen", stop)
    finished = _json(path.with_name("finished.json"))
    finished = finished if isinstance(finished, dict) else {}
    read, pinned = finished.get("read"), finished.get("pinned")
    for key, stop in (read.items() if isinstance(read, dict) else ()):
        if isinstance(key, str) and _stamp(stop):
            put(key, "read", stop)
    for key in (pinned if isinstance(pinned, list) else ()):
        if isinstance(key, str):
            put(key, "pinned", True)
    return out


def load(path=None):
    """`{key: record}`. A file that exists and cannot be read is empty, and is
    not rebuilt from the old files; only a file that does not exist is."""
    path = Path(path or store())
    try:
        with path.open(encoding="utf-8") as fh:
            return _clean(json.load(fh))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return {}
    with _LOCK:
        # Another thread may have built it while this one waited.
        try:
            with path.open(encoding="utf-8") as fh:
                return _clean(json.load(fh))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            return {}
        return _save(_clean(_imported(path)), path)


def _save(state, path):
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
        pass
    return state


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


def keys(path=None):
    """Every session the file holds a mark for."""
    return set(load(path))


def mark(key, stamp, read, path=None):
    """You looked at this session as it is at the stop `stamp` and, when
    `read`, read its handover: both in one write. `read` off leaves an
    existing read stop alone."""
    if not key or not stamp:
        return load(path)
    with _LOCK:
        state = load(path)
        record = state.setdefault(key, {})
        record["seen"] = stamp
        if read:
            record["read"] = stamp
        return _save(state, path or store())


def pin(key, on, path=None):
    """Pin a session open as a full tile, or let it shrink again."""
    if not key:
        return load(path)
    with _LOCK:
        state = load(path)
        if on:
            state.setdefault(key, {})["pinned"] = True
        elif key in state:
            state[key].pop("pinned", None)
            if not state[key]:
                del state[key]
        return _save(state, path or store())


def forget(drop, path=None):
    """Drop every record of the sessions in `drop` (and nothing else), so the
    file cannot grow forever and a pin ends with its session.

    Which sessions are gone is the round's decision (`poll.round`), and never
    those of a provider that missed the poll: forgetting its marks would bring
    everything you had already read back as `ready` when it returns. The file
    is read again under the lock, so a mark or a pin that landed since the
    round began survives. A key not here is nothing.
    """
    with _LOCK:
        state = load(path)
        kept = {key: record for key, record in state.items() if key not in drop}
        if len(kept) != len(state):
            _save(kept, path or store())
        return kept
