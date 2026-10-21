"""A Paste: a titled text a session leaves for the person on its card.

Sessions used to put what the person had to paste elsewhere on the system
clipboard, one slot shared by every session, so the text belonged to whichever
session wrote last. A Paste waits on the page instead, until the person ticks it
done or the session withdraws it because it saw the thing happen. Copying never
removes one.

Kept beside the session lines (`lines.store()`), in a folder of its own: the
lines of a session that is gone are swept away (`lines.forget`), and a Paste
must outlive its session. Never under `~/.claude` or anything else that is
committed or synced.

Two files for a Paste, `<id>.txt` (the text, bytes as they were) and `<id>.json`
(who, title, first line, copied). The record is what makes a Paste exist and is
written last, so the roster, which reads the records every poll, never reads a
text and never sees a half-made one.
"""
import argparse
import contextlib
import fcntl
import json
import re
import secrets
import sys
import time
from pathlib import Path

import lines

# A runaway file stays off the page.
MAX_BYTES = 100_000
TITLE_MAX = 80
FIRST_MAX = 160
RECORD_MAX = 16 * 1024
ID = re.compile(r"[0-9a-f]{16}")


class Refused(Exception):
    """A Paste that was not made, or a change that was not made. The text says why."""


def store():
    return lines.store().parent / "pastes"


def _root(root):
    return Path(root) if root else store()


def _clip(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return _clip(line, FIRST_MAX)
    return ""


def read_text_file(path):
    """The text in a file, or `Refused` saying what is wrong with it."""
    # Not a pipe, which waits for ever, nor a device, which has no end.
    data = lines.read_plain(str(path), MAX_BYTES + 1)
    if data is None:
        raise Refused(f"{path} is not a file that can be read")
    if len(data) > MAX_BYTES:
        raise Refused(f"{path} is larger than {MAX_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(f"{path} is not UTF-8 text") from None
    if "\x00" in text:
        raise Refused(f"{path} is not text")
    if not text.lstrip("\ufeff").strip():
        raise Refused(f"{path} is empty")
    return text


def _name(value, what):
    if not isinstance(value, str) or not lines.SAFE.fullmatch(value):
        raise Refused(f"not a {what}")
    return value


def create(session_id, title, path, root=None, provider=None):
    """Leave a Paste on a session's card. Returns its id.

    A session is one provider and one id; two providers may use the same id.
    Say the `provider` and the Paste belongs to that session alone. Without it
    the Paste belongs to every session with that id, as it did before."""
    _name(session_id, "session id")
    if provider is not None:
        _name(provider, "provider name")
    title = _clip(title or "", TITLE_MAX)
    if not title:
        raise Refused("a Paste needs a title")
    text = read_text_file(path)
    root = _root(root)
    pid = secrets.token_hex(8)
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not lines.write_atomic(root / f"{pid}.txt", text):
            raise Refused("could not write the Paste")
        record = {"id": pid, "session": session_id, "title": title, "first": _first_line(text),
                  "at": time.time_ns(), "secret": False, "copied": False}
        if provider is not None:
            record["provider"] = provider
        if not lines.write_atomic(root / f"{pid}.json", json.dumps(record)):
            _unlink(root / f"{pid}.txt")
            raise Refused("could not write the Paste")
    except OSError as err:
        raise Refused(f"could not write the Paste: {err.strerror}") from None
    return pid


def _unlink(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as err:
        raise Refused(f"could not remove the Paste: {err.strerror}") from None


@contextlib.contextmanager
def _changing(root):
    """One change to a Paste at a time, across the server's threads and the
    command's processes: a copy mark read before a done and written after it
    would bring the record back without its text."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(root / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _record(pid, root=None):
    if not isinstance(pid, str) or not ID.fullmatch(pid):
        return None
    # Read on every poll, under the lock the page waits on: bounded in time.
    data = lines.read_bounded(str(_root(root) / f"{pid}.json"), RECORD_MAX)
    try:
        got = json.loads(data.decode("utf-8")) if data else None
    except (ValueError, RecursionError):
        return None
    if not isinstance(got, dict) or got.get("id") != pid:
        return None
    if not isinstance(got.get("session"), str) or not isinstance(got.get("title"), str):
        return None
    return got


def _shown(got):
    return {"id": got["id"], "title": got["title"], "first": str(got.get("first") or ""),
            "secret": got.get("secret") is True, "copied": got.get("copied") is True}


def belongs_to(made_for, provider):
    """A Paste made for no provider belongs to every session with its id; one
    made for a provider, to that provider's session alone. A caller that names
    no provider is every provider."""
    return provider is None or not isinstance(made_for, str) or made_for == provider


def waiting(root=None):
    """Every Paste not yet done, as `(session id, provider or None, what the page
    shows)`, in the order they were made."""
    root = _root(root)
    try:
        names = list(root.glob("*.json"))
    except OSError:
        return []
    found = [r for r in (_record(p.stem, root) for p in names) if r]
    found.sort(key=lambda r: (r.get("at") if isinstance(r.get("at"), int) else 0, r["id"]))
    return [(r["session"], r["provider"] if isinstance(r.get("provider"), str) else None, _shown(r))
            for r in found]


# A text with no record is a `create` that is still writing, or one that died.
# Only the second is old.
SWEEP_AFTER = 600


def sweep(root=None, after=SWEEP_AFTER):
    """Remove what a crash left: a text whose record never came, and the
    half-written files of an atomic write. A text whose record exists is
    never touched, readable or not; neither is a young one."""
    root = _root(root)
    try:
        found = list(root.glob("*.txt")) + list(root.glob("*.tmp"))
    except OSError:
        return
    now = time.time()
    for path in found:
        try:
            if path.suffix == ".txt" and (root / f"{path.stem}.json").exists():
                continue
            if now - path.stat().st_mtime > after:
                path.unlink()
        except OSError:
            pass


def text(pid, root=None):
    """The full text of a Paste, exactly as it was left, or None."""
    if _record(pid, root) is None:
        return None
    return lines.read_plain(str(_root(root) / f"{pid}.txt"), MAX_BYTES + 1)


def copied(pid, root=None):
    """Mark it copied. It stays. False when there is no such Paste."""
    root = _root(root)
    try:
        with _changing(root):
            got = _record(pid, root)
            if got is None:
                return False
            got["copied"] = True
            if not lines.write_atomic(root / f"{pid}.json", json.dumps(got)):
                raise Refused("could not write the Paste")
    except OSError as err:
        raise Refused(f"could not write the Paste: {err.strerror}") from None
    return True


def done(pid, root=None, session_id=None, provider=None):
    """Remove a Paste. False when there is none, or when it is not `session_id`'s
    (nor `provider`'s, when both the Paste and the caller name one).
    `Refused` when it is there and cannot be removed."""
    root = _root(root)
    try:
        with _changing(root):
            got = _record(pid, root)
            if got is None or (session_id is not None and got["session"] != session_id):
                return False
            if not belongs_to(got.get("provider"), provider):
                return False
            # The text first. Whatever fails after that leaves a Paste on the card,
            # which can be ticked again; the other way round leaves a text nobody sees.
            _unlink(root / f"{pid}.txt")
            _unlink(root / f"{pid}.json")
    except OSError as err:
        raise Refused(f"could not remove the Paste: {err.strerror}") from None
    return True


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    p = argparse.ArgumentParser(prog="paste", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="leave a Paste; prints its id")
    c.add_argument("session")
    c.add_argument("--provider", help="claude, codex...: the Paste then belongs to that provider's session alone")
    c.add_argument("--title", required=True)
    c.add_argument("file", help="the text, read from this file and never from an argument")
    w = sub.add_parser("withdraw", help="take back a Paste whose use you have seen")
    w.add_argument("session")
    w.add_argument("--provider")
    w.add_argument("id")
    args = p.parse_args(argv)
    try:
        if args.cmd == "create":
            print(create(args.session, args.title, args.file, provider=args.provider), file=out)
        elif not done(args.id, session_id=args.session, provider=args.provider):
            raise Refused(f"no Paste {args.id!r} on session {args.session!r}")
    except Refused as why:
        print(f"paste: {why}", file=err)
        return 1
    return 0
