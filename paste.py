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
    if not text.strip():
        raise Refused(f"{path} is empty")
    return text


def create(session_id, title, path, root=None):
    """Leave a Paste on a session's card. Returns its id."""
    if not isinstance(session_id, str) or not lines.SAFE.fullmatch(session_id):
        raise Refused("not a session id")
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
        if not lines.write_atomic(root / f"{pid}.json", json.dumps(record)):
            _unlink(root / f"{pid}.txt")
            raise Refused("could not write the Paste")
    except OSError as err:
        raise Refused(f"could not write the Paste: {err.strerror}") from None
    return pid


def _unlink(path):
    try:
        path.unlink()
    except OSError:
        pass


def _record(pid, root=None):
    if not isinstance(pid, str) or not ID.fullmatch(pid):
        return None
    data = lines.read_plain(str(_root(root) / f"{pid}.json"), RECORD_MAX)
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


def waiting(root=None):
    """Every Paste not yet done, by session id, each list in the order they were made."""
    root = _root(root)
    try:
        names = list(root.glob("*.json"))
    except OSError:
        return {}
    found = [r for r in (_record(p.stem, root) for p in names) if r]
    found.sort(key=lambda r: (r.get("at") if isinstance(r.get("at"), int) else 0, r["id"]))
    by = {}
    for r in found:
        by.setdefault(r["session"], []).append(_shown(r))
    return by


def text(pid, root=None):
    """The full text of a Paste, exactly as it was left, or None."""
    if _record(pid, root) is None:
        return None
    return lines.read_plain(str(_root(root) / f"{pid}.txt"), MAX_BYTES + 1)


def copied(pid, root=None):
    """Mark it copied. It stays. False when there is no such Paste."""
    got = _record(pid, root)
    if got is None:
        return False
    got["copied"] = True
    return lines.write_atomic(_root(root) / f"{pid}.json", json.dumps(got))


def done(pid, root=None, session_id=None):
    """Remove a Paste. False when there is none, or when it is not `session_id`'s."""
    got = _record(pid, root)
    if got is None or (session_id is not None and got["session"] != session_id):
        return False
    root = _root(root)
    _unlink(root / f"{pid}.json")       # the record first: without it there is no Paste
    _unlink(root / f"{pid}.txt")
    return True


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    p = argparse.ArgumentParser(prog="paste", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="leave a Paste; prints its id")
    c.add_argument("session")
    c.add_argument("--title", required=True)
    c.add_argument("file", help="the text, read from this file and never from an argument")
    w = sub.add_parser("withdraw", help="take back a Paste whose use you have seen")
    w.add_argument("session")
    w.add_argument("id")
    args = p.parse_args(argv)
    try:
        if args.cmd == "create":
            print(create(args.session, args.title, args.file), file=out)
        elif not done(args.id, session_id=args.session):
            raise Refused(f"no Paste {args.id!r} on session {args.session!r}")
    except Refused as why:
        print(f"paste: {why}", file=err)
        return 1
    return 0
