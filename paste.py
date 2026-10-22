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

A secret Paste (the session said so, or `credentials.looks_secret` found a
token or a password in the text) has no `.txt`: its text is in the login
keyring (`vault.py`) and the record, which has no first line either, only says
so. There is no plain-file fallback: with the keyring out of reach the command
refuses. Two things then have to go together, the keyring item and the record.
Done removes the item first, so a failure leaves the record on the card, which
can be ticked again; the record is written last when making one, and if that
fails the item is taken back. `paste sweep` (`sweep_keyring`) finds what a crash left between
the two.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import stat
import re
import secrets
import sys
import time
from pathlib import Path

import credentials
import lines
import vault

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


def _scope(root):
    """Which store a keyring item belongs to: its place, so that another store never touches it."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


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


def create(session_id, title, path, root=None, provider=None, secret=False):
    """Leave a Paste on a session's card. Returns its id.

    A session is one provider and one id; two providers may use the same id.
    Say the `provider` and the Paste belongs to that session alone. Without it
    the Paste belongs to every session with that id, as it did before."""
    _name(session_id, "session id")
    if provider is not None:
        _name(provider, "provider name")
    # The whole title is looked at, then clipped: a token cut in two by the clip no longer looks
    # like one, and its first half would be on the card and in the roster, in the clear.
    raw_title = title or ""
    title = _clip(raw_title, TITLE_MAX)
    if not title:
        raise Refused("a Paste needs a title")
    # Also as the card shows it, its white space collapsed.
    if credentials.looks_secret(raw_title) or credentials.looks_secret(" ".join(raw_title.split())):
        raise Refused("the title looks like a secret; the card shows it in the clear")
    text = read_text_file(path)
    root = _root(root)
    pid = secrets.token_hex(8)
    if secret or credentials.looks_secret(text):
        return _create_secret(root, pid, session_id, title, text, provider)
    try:
        # Held across both writes, so that `sweep` never sees the text alone, however long the
        # creator stalls between them.
        with _changing(root):
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


def _create_secret(root, pid, session_id, title, text, provider=None):
    record = {"id": pid, "session": session_id, "title": title, "first": "",
              "at": time.time_ns(), "secret": True, "copied": False}
    if provider is not None:
        record["provider"] = provider
    try:
        # Asked before anything is created on disk: an unreachable keyring leaves nothing behind,
        # not even the folder and its lock. (A keyring that goes away between this and the put
        # leaves the empty lock file and no Paste: no text, no record.)
        try:
            vault.ids(_scope(root))
        except vault.Unavailable as why:
            raise Refused(f"{why}; no Paste was made") from None
        # Held until the record is down, so that `sweep` never sees the item alone.
        with _changing(root):
            try:
                vault.put(pid, text, _scope(root))
            except vault.Unsure as why:
                # The reply was lost, the item may not be: taken back, or named so it is not silent.
                try:
                    taken = vault.delete(pid, _scope(root))
                except vault.Unavailable:
                    taken = False
                if taken:
                    raise Refused(f"{why}; no Paste was made") from None
                raise Refused(f"{why}; no Paste was made, but the keyring may still keep an item "
                              f"{pid}; `paste sweep` removes it") from None
            except vault.Unavailable as why:
                raise Refused(f"{why}; no Paste was made") from None
            if lines.write_atomic(root / f"{pid}.json", json.dumps(record)):
                return pid
            try:
                vault.delete(pid, _scope(root))
            except vault.Unavailable:
                raise Refused(f"could not write the Paste, and its keyring item {pid} could not be taken "
                              "back; `paste sweep` removes it") from None
    except OSError as err:
        raise Refused(f"could not write the Paste: {err.strerror}") from None
    raise Refused("could not write the Paste")


def _unlink(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as err:
        raise Refused(f"could not remove the Paste: {err.strerror}") from None


@contextlib.contextmanager
def _changing(root, wait=True):
    """One change to a Paste at a time, across the server's threads and the
    command's processes: a copy mark read before a done and written after it
    would bring the record back without its text. `wait=False` raises BlockingIOError
    instead of waiting for the lock."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Opened so that a lock that is a FIFO or a link to one cannot stall the caller; only the
    # flock itself may wait.
    fd = os.open(root / ".lock", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("the lock is not a file")
        fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _record(pid, root=None, patient=False):
    """The record, or None. The poll reads with a time limit (a slow read is None, as if absent);
    a caller that changes a Paste or acts on absence (`copied`, `done`, `sweep_keyring`, the note
    after `create`) must be `patient`."""
    if not isinstance(pid, str) or not ID.fullmatch(pid):
        return None
    # Read on every poll, under the lock the page waits on: bounded in time.
    read = lines.read_plain if patient else lines.read_bounded
    data = read(str(_root(root) / f"{pid}.json"), RECORD_MAX)
    try:
        got = json.loads(data.decode("utf-8")) if data else None
    except (ValueError, RecursionError):
        return None
    if not isinstance(got, dict) or got.get("id") != pid:
        return None
    if not isinstance(got.get("session"), str) or not isinstance(got.get("title"), str):
        return None
    return got


def _is_secret(record):
    return record.get("secret") is True


def _shown(got):
    secret = _is_secret(got)
    # Never the first line of a secret, whatever a record says.
    return {"id": got["id"], "title": got["title"], "first": "" if secret else str(got.get("first") or ""),
            "secret": secret, "copied": got.get("copied") is True}


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


def _present(path):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True            # cannot tell: then it is not ours to remove
    return True


def sweep(root=None, after=SWEEP_AFTER):
    """Remove what a crash left: a text whose record never came, and the
    half-written files of an atomic write. A text whose record exists is
    never touched, readable or not; neither is a young one."""
    root = _root(root)
    try:
        found = list(root.glob("*.txt")) + list(root.glob("*.tmp"))
    except OSError:
        return
    if not found:
        return
    # A creator holds the lock from its text to its record. If the lock is taken, someone is
    # mid-change and the sweep waits for the next poll rather than stall this one.
    try:
        with _changing(root, wait=False):
            now = time.time()
            for path in found:
                try:
                    # lstat, never following a link: a probe that follows one into a
                    # filesystem that does not answer would stall the roster poll.
                    if path.suffix == ".txt" and _present(root / f"{path.stem}.json"):
                        continue
                    if now - os.lstat(path).st_mtime > after:
                        path.unlink()
                except OSError:
                    pass
    except OSError:         # a busy lock (BlockingIOError) or a store we cannot write to
        return


def text(pid, root=None):
    """The full text of a Paste, exactly as it was left, or None."""
    got = _record(pid, root)
    if got is None:
        return None
    if _is_secret(got):
        try:
            kept = vault.get(pid, _scope(_root(root)))
        except vault.Unavailable as why:
            raise Refused(str(why)) from None
        return None if kept is None else kept.encode("utf-8")
    return lines.read_plain(str(_root(root) / f"{pid}.txt"), MAX_BYTES + 1)


def copied(pid, root=None):
    """Mark it copied. It stays. False when there is no such Paste."""
    root = _root(root)
    try:
        with _changing(root):
            got = _record(pid, root, patient=True)
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
            got = _record(pid, root, patient=True)
            if got is None or (session_id is not None and got["session"] != session_id):
                return False
            if not belongs_to(got.get("provider"), provider):
                return False
            # The text first. Whatever fails after that leaves a Paste on the card,
            # which can be ticked again; the other way round leaves a text nobody sees.
            if _is_secret(got):
                try:
                    vault.delete(pid, _scope(root))
                except vault.Unavailable as why:
                    raise Refused(f"could not remove the Paste: {why}") from None
            else:
                _unlink(root / f"{pid}.txt")
            _unlink(root / f"{pid}.json")
    except OSError as err:
        raise Refused(f"could not remove the Paste: {err.strerror}") from None
    return True


def sweep_keyring(root=None):
    """What a crash can leave between a keyring item and its record, undone or named:
    items nothing points at are removed, records without an item are named.
    Returns (ids removed, ids of records whose item is gone)."""
    root = _root(root)
    try:
        with _changing(root):
            try:
                items = set(vault.ids(_scope(root)))
            except vault.Unavailable as why:
                raise Refused(str(why)) from None
            records = {r["id"] for r in (_record(p.stem, root, patient=True) for p in root.glob("*.json"))
                       if r and _is_secret(r)}
            # A record file that is there but unreadable right now still points at its item:
            # only an id with no record file at all is a stray. A deleted item cannot come back.
            pointed = records | {p.stem for p in root.glob("*.json") if _present(p)}
            stray = sorted(items - pointed)
            for pid in stray:
                try:
                    vault.delete(pid, _scope(root))
                except vault.Unavailable as why:
                    raise Refused(f"could not remove keyring item {pid}: {why}") from None
            return stray, sorted(records - items)
    except OSError as err:
        raise Refused(f"could not sweep: {err.strerror}") from None


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    p = argparse.ArgumentParser(prog="paste", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="leave a Paste; prints its id")
    c.add_argument("session")
    c.add_argument("--provider", help="claude, codex...: the Paste then belongs to that provider's session alone")
    c.add_argument("--title", required=True)
    c.add_argument("--secret", action="store_true",
                   help="keep the text in the login keyring, never in a file (a token or password in "
                        "the text is recognised without this)")
    c.add_argument("file", help="the text, read from this file and never from an argument")
    w = sub.add_parser("withdraw", help="take back a Paste whose use you have seen")
    w.add_argument("session")
    w.add_argument("--provider")
    w.add_argument("id")
    sub.add_parser("sweep", help="remove keyring items no Paste points at; name Pastes whose item is gone")
    args = p.parse_args(argv)
    try:
        if args.cmd == "create":
            pid = create(args.session, args.title, args.file, provider=args.provider, secret=args.secret)
            print(pid, file=out)
            if _is_secret(_record(pid, patient=True) or {}):
                print(f"paste: kept in the keyring as a secret; {args.file} still holds the text, delete it", file=err)
        elif args.cmd == "sweep":
            stray, lost = sweep_keyring()
            for pid in stray:
                print(f"removed keyring item {pid}: no Paste points at it", file=out)
            for pid in lost:
                print(f"Paste {pid} has no keyring item: it cannot be read; tick it done", file=out)
        elif not done(args.id, session_id=args.session, provider=args.provider):
            raise Refused(f"no Paste {args.id!r} on session {args.session!r}")
    except Refused as why:
        print(f"paste: {why}", file=err)
        return 1
    return 0
