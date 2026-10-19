"""What the overview remembers about finished sessions.

Two facts per session, kept beside `seen.json` and not in `config.json`: that
file is yours to hand-edit, and this one changes every time you click.

- **read**: the stop whose handover you read in the overview. Like the seen
  mark it is not "you saw this session" but *when it stopped*, so a session
  that works again and stops again has a handover nobody has read, with
  nothing to expire.
- **pinned**: the sessions you pinned open as a full tile, until you unpin
  them or the session closes.

Why `read` is not `seen.json`: a session may become a pill only on a handover
that was shown to you on the new page. The seen marks from before the
overview say "you clicked this row", which a jump that failed used to write as
well, and the old row said nothing of what the session had told you. They keep
driving the chime and the `ready` flag exactly as before; they just do not
count as having read the handover here. `fleet.mark_seen` writes both.
"""
import json
import threading
from pathlib import Path

import seen

# The server answers on threads, and every change reads the file, edits it and
# writes it back: two at once would drop one of them.
_LOCK = threading.RLock()


def store():
    return seen.store().with_name("finished.json")


def _stamp(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load(path=None):
    """`{"read": {key: stop}, "pinned": [key, ...]}`. Anything in the file that is
    not one of those is left out, and a file that cannot be read is empty."""
    try:
        with (path or store()).open(encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        got = None
    got = got if isinstance(got, dict) else {}
    read, pinned = got.get("read"), got.get("pinned")
    return {
        "read": {k: v for k, v in read.items() if isinstance(k, str) and _stamp(v)}
        if isinstance(read, dict) else {},
        "pinned": list(dict.fromkeys(k for k in pinned if isinstance(k, str)))
        if isinstance(pinned, list) else [],
    }


def save(state, path=None):
    """Write the state, atomically. Never raises: forgetting what you read is a
    smaller problem than a page that will not load."""
    path = Path(path or store())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
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


def mark_read(key, stamp, path=None):
    """You read this session's handover, as it is at the stop `stamp`."""
    if not key or not stamp:
        return load(path)
    with _LOCK:
        state = load(path)
        state["read"][key] = stamp
        return save(state, path)


def is_read(key, stamp, state):
    """Have you read the handover of this very stop?"""
    return bool(stamp) and state["read"].get(key) == stamp


def pin(key, on, path=None):
    """Pin a session open as a full tile, or let it shrink again."""
    with _LOCK:
        state = load(path)
        if on and key not in state["pinned"]:
            state["pinned"].append(key)
        elif not on:
            state["pinned"] = [k for k in state["pinned"] if k != key]
        return save(state, path)


def forget(live, path=None, *, answered=None):
    """Drop what belongs to sessions that no longer exist, so the file cannot
    grow forever and a pin ends with its session.

    Only for the providers that answered this round, as for the seen marks: a
    provider that missed a poll has no sessions in `live`, and forgetting its
    pins would turn every pill of it back into a tile when it returns.
    """
    def gone(key):
        return key not in live and (answered is None or key.partition(":")[0] in answered)

    with _LOCK:
        state = load(path)
        kept = {"read": {k: v for k, v in state["read"].items() if not gone(k)},
                "pinned": [k for k in state["pinned"] if not gone(k)]}
        if kept != state:
            save(kept, path)
        return kept
