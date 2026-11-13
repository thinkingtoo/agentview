"""The merge desk's file: one item at a time, never the whole file.

The desk is a sheaf page, `merge-desk.md` under AgentView's state folder. The
person's comments and ticks live in that same file, so nothing here ever writes
it from a copy read earlier: every change is read, spliced and written under one
lock (`edit`), and only the block of the item it is about is touched. Another
item's bytes, its comment markers included, come out as they went in.

An item is a task line, `- [ ] Merge owner/repo#272: what it does`, with indented
sub-lines under it. Its identity is that key, `owner/repo#272` (an Install item:
`install:<tool>`), and the commit pinned in its `Pinned commit:` sub-line, never
its place in the file or its words. A block runs from its task line up to the
next top-level list item, heading or end of file.

Ticket 02 (hand over, withdraw) calls `put_item` and `drop_item`; the watcher
(03) reads `items`, and Install items (04) and the tidy (08) go through the same
two calls, with `section="install"` for the former.
"""
import contextlib
import fcntl
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import lines

NAME = "merge-desk.md"
SECTIONS = {
    "merge": "## Pull requests waiting for your merge",
    "install": "## Local installs waiting for you",
}
SKELETON = """# Merge desk: what waits for your hand to merge, deploy or install

Each item below is finished work that only you can release. Press the button on an item
to release it at the commit that was reviewed; the result is written under it. An empty
list means nothing waits.

""" + SECTIONS["merge"] + "\n"

TASK = re.compile(r"^- \[([ xX])\] (?:(?:Merge|Deploy) ([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)|Install ([^\s:]+))(?::|$)")
PINNED = re.compile(r"^\s+- Pinned commit: ([0-9a-f]{7,40})\b", re.M)
HEADING = re.compile(r"^#{1,6} ")
TOP_ITEM = re.compile(r"^[-*+] ")


@dataclass
class Item:
    key: str
    ticked: bool
    pinned: str
    block: str


def key_of(first_line):
    """The key a task line carries, or None when it is not a desk item."""
    got = TASK.match(first_line)
    if not got:
        return None
    return got.group(2) or "install:" + got.group(3)


def path():
    return lines.store().parent / NAME


_held = threading.local()


@contextlib.contextmanager
def locked(file=None):
    """The one writer of the desk file. The watcher, the scan and the tidy take it too.
    Taking it again inside the same thread (a caller that also logs under it) is allowed."""
    file = Path(file) if file else path()
    if getattr(_held, "depth", 0):
        _held.depth += 1
        try:
            yield file
        finally:
            _held.depth -= 1
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file.parent / ".merge-desk.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        _held.depth = 1
        try:
            yield file
        finally:
            _held.depth = 0


def _read(file):
    try:
        return file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SKELETON


def _spans(text):
    """(key, start, end) of every desk item, as offsets into `text`."""
    out, offset, open_ = [], 0, None
    for line in text.splitlines(keepends=True):
        top = TOP_ITEM.match(line) or HEADING.match(line)
        if top and open_ is not None:
            out.append((*open_, offset))
            open_ = None
        key = key_of(line)
        if key:
            open_ = (key, offset)
        offset += len(line)
    if open_ is not None:
        out.append((*open_, offset))
    return out


def parse(text):
    found = []
    for key, start, end in _spans(text):
        block = text[start:end]
        pin = PINNED.search(block)
        found.append(Item(key, block[3] in "xX", pin.group(1) if pin else "", block))
    return found


def items(file=None):
    """The items on the page now, in page order. Read-only: no lock needed."""
    return parse(_read(Path(file) if file else path()))


def put(text, key, block, section="merge"):
    """`text` with the item `key` set to `block`: replaced where it stands, else
    added at the end of its section. A section that is not there yet is made."""
    if not block.endswith("\n"):
        block += "\n"
    for k, start, end in _spans(text):
        if k == key:
            return text[:start] + block + text[end:]
    heading = SECTIONS[section]
    if heading not in text:
        text = text.rstrip("\n") + "\n\n" + heading + "\n"
    at = text.index(heading) + len(heading) + 1
    nxt = re.compile(r"^## ", re.M).search(text, at)
    end = nxt.start() if nxt else len(text)
    body = text[at:end]
    tail = body[len(body.rstrip("\n")):]            # the blank line before the next heading
    new = body.rstrip("\n") + ("\n" if body.strip() else "") + block
    return text[:at] + new + (tail if nxt else "") + text[end:]


def drop(text, key):
    for k, start, end in _spans(text):
        if k == key:
            return text[:start] + text[end:]
    return text


def edit(change, file=None):
    """Read the file fresh under the lock, apply `change(text) -> text`, write it whole
    or not at all. Returns what `change` returned about it (the new text)."""
    with locked(file) as f:
        before = _read(f)
        after = change(before)
        if after != before and not lines.write_atomic(f, after):
            raise OSError(f"could not write {f}")
        return after


def put_item(key, block, section="merge", file=None):
    return edit(lambda t: put(t, key, block, section), file)


def drop_item(key, file=None):
    return edit(lambda t: drop(t, key), file)
