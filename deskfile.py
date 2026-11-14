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

`put_item` and `drop_item` are the two calls that change an item; the watcher that
merges ticked items reads `items`, and Install items go through the same two calls
with `section="install"`.

Lines inside a `<!-- ... -->` comment (sheaf keeps the person's comments in the file,
and a comment may hold a list line or a heading) are never taken for the start or end
of an item or a section.
"""
import contextlib
import fcntl
import hashlib
import os
import re
import sys
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
AFTER = re.compile(r"^\s+- Pinned commit: [^\n]*; must go after #(\d+)", re.M)
HEADING = re.compile(r"^#{1,6} ")
TOP_ITEM = re.compile(r"^[-*+] ")


@dataclass
class Item:
    key: str
    ticked: bool
    pinned: str
    block: str
    after: int = 0          # the PR of the same repo that must be merged first; 0 for none


def key_of(first_line):
    """The key a task line carries, or None when it is not a desk item."""
    got = TASK.match(first_line)
    if not got:
        return None
    return got.group(2) or "install:" + got.group(3)


def path():
    return lines.store().parent / NAME


_held = threading.local()


def sheaf_lock_path(file):
    """The lock sheaf takes around its own read-and-replace of this document: sheaf ticks
    boxes and writes comments in the same file, so a writer that wants no lost update takes
    it too. `<runtime>/locks/<first 12 hex of sha1 of the resolved path>.lock`, as sheaf's
    `source.lock_key` names it."""
    run = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(run) / "sheaf" if sys.platform != "darwin" and run and os.path.isabs(run) else Path(f"/tmp/sheaf-{os.getuid()}")
    key = hashlib.sha1(os.fsencode(Path(file).resolve())).hexdigest()[:12]
    return base / "locks" / (key + ".lock")


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
    theirs = sheaf_lock_path(file)
    theirs.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(file.parent / ".merge-desk.lock", "a") as ours, open(theirs, "a") as sheafs:
        fcntl.flock(ours, fcntl.LOCK_EX)
        fcntl.flock(sheafs, fcntl.LOCK_EX)
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


def _walk(text):
    """(offset, line, inside) for each line; `inside` is true when the line starts
    inside an HTML comment."""
    offset, inside = 0, False
    for line in text.splitlines(keepends=True):
        yield offset, line, inside
        for mark in re.findall(r"<!--|-->", line):
            inside = mark == "<!--"
        offset += len(line)


def _spans(text):
    """(key, start, end) of every desk item, as offsets into `text`."""
    out, open_ = [], None
    for offset, line, inside in _walk(text):
        if inside:
            continue
        top = TOP_ITEM.match(line) or HEADING.match(line)
        if top and open_ is not None:
            out.append((*open_, offset))
            open_ = None
        key = key_of(line)
        if key:
            open_ = (key, offset)
    end = len(text)
    if open_ is not None:
        out.append((*open_, end))
    return out


def parse(text):
    found = []
    for key, start, end in _spans(text):
        block = text[start:end]
        visible = re.sub(r"<!--.*?-->", "", block, flags=re.S)              # a comment pins nothing, and orders nothing
        pin, order = PINNED.search(visible), AFTER.search(visible)
        found.append(Item(key, block[3] in "xX", pin.group(1) if pin else "", block, int(order.group(1)) if order else 0))
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
        if k.lower() == key.lower():            # GitHub names are not case-sensitive: `Owner/Repo#5` is `owner/repo#5`
            return text[:start] + block + text[end:]
    heading = SECTIONS[section]
    at = _heading_end(text, heading)
    if at is not None and not text.endswith("\n") and at == len(text):
        text += "\n"
        at += 1
    if at is None:
        text = text.rstrip("\n") + "\n\n" + heading + "\n"
        at = len(text)
    end = next((o for o, line, inside in _walk(text) if o >= at and not inside and line.startswith("## ")),
               len(text))
    nxt = end < len(text)
    body = text[at:end]
    tail = body[len(body.rstrip("\n")):]            # the blank line before the next heading
    new = body.rstrip("\n") + ("\n" if body.strip() else "") + block
    return text[:at] + new + (tail if nxt else "") + text[end:]


def _heading_end(text, heading):
    """Offset just after the heading's own line (outside any comment), or None."""
    for offset, line, inside in _walk(text):
        if not inside and line.rstrip("\n") == heading:
            return offset + len(line)
    return None


def drop(text, key):
    for k, start, end in _spans(text):
        if k == key:
            return text[:start] + text[end:]
    return text


RESULT = re.compile(r"^  - (?:(?:Already merged|Merged)(?: as [0-9a-f]{7})? at \d\d:\d\d|Not merged: .*"
                    r"|(?:Already installed|Installed) as [0-9a-f]{7} at \d\d:\d\d.*|Not installed: .*)$")


def settle(text, key, result, untick=False, pinned=None):
    """`text` with the result of a press written as the last sub-line of item `key` (the
    last result sub-line of an earlier press is replaced), and its box unticked when `untick`; with `pinned`, only an item still pinned at that commit. Text with
    no such item comes back as it was."""
    for k, start, end in _spans(text):
        if k != key:
            continue
        block = text[start:end]
        if pinned is not None and parse(block)[0].pinned != pinned:      # the item was handed over again meanwhile
            return text
        body = block.rstrip("\n")
        tail = block[len(body):] or "\n"
        kept = body.split("\n")
        at = len(kept) - 1                                              # our line is always the last one, bar the person's comments after it
        while at > 0 and re.fullmatch(r"\s*<!--.*-->\s*", kept[at]):
            at -= 1
        if RESULT.match(kept[at]):
            del kept[at]
        if untick and kept[0][3] in "xX":
            kept[0] = kept[0][:3] + " " + kept[0][4:]
        return text[:start] + "\n".join(kept + ["  - " + result]) + tail + text[end:]
    return text


def edit(change, file=None):
    """Read the file fresh under the lock, apply `change(text) -> text`, write it whole
    or not at all. Returns what `change` returned about it (the new text)."""
    with locked(file) as f:
        # Sheaf writes this file too, with a lock of its own: a tick or a comment that lands
        # between our read and our replace would be lost, so look again just before replacing.
        for _ in range(5):
            before = _read(f)
            after = change(before)
            if after == before:
                return after
            if _read(f) != before:
                continue
            if not lines.write_atomic(f, after):
                raise OSError(f"could not write {f}")
            return after
        raise OSError(f"{f} keeps changing under us; try again")


def put_item(key, block, section="merge", file=None):
    return edit(lambda t: put(t, key, block, section), file)


def drop_item(key, file=None):
    return edit(lambda t: drop(t, key), file)
