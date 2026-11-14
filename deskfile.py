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
import copy
import fcntl
import hashlib
import html
import json
import os
import re
import sys
import threading
from collections import Counter
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
    ships: list | None = None   # the lines under `What ships:` (a Deploy item), None when the item has none


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


SHIPS_HEADER = "  - What ships:"


def ships_of(block):
    """The sub-list under `What ships:` (four spaces of indent taken off), or None when the block has none. A bullet
    is what stands before the first `<!--` of its line: a thread on it, and what the person typed after the thread,
    are not part of it."""
    out, inside = None, False
    for line in _logical(block):
        head = _split(line)[0].rstrip("\n")
        if head.rstrip() == SHIPS_HEADER:
            out, inside = [], True
        elif inside and head.startswith("    ") and head.strip():
            out.append(head[4:].rstrip())
        elif inside and not head.strip() and "<!--" in line:
            continue                                    # a comment on a line of its own does not end the list
        elif inside:
            inside = False
    return out


def parse(text):
    found = []
    for key, start, end in _spans(text):
        block = text[start:end]
        visible = re.sub(r"<!--.*?-->", "", block, flags=re.S)              # a comment pins nothing, and orders nothing
        pin, order = PINNED.search(visible), AFTER.search(visible)
        found.append(Item(key, block[3] in "xX", pin.group(1) if pin else "", block, int(order.group(1)) if order else 0, ships_of(block)))
    return found


def items(file=None):
    """The items on the page now, in page order. Read-only: no lock needed."""
    return parse(_read(Path(file) if file else path()))


# The lines AgentView writes under an item, by kind. A line is its own only in the exact shape it writes it;
# anything else under the item is the person's and stays.
OWN_LINES = (("rec", re.compile(r"  - Recommendation: ")),
             ("pin", re.compile(r"  - Pinned commit: [0-9a-f]{7,40}\b")),
             ("by", re.compile(r"  - Handed over by .*, \d{4}-\d\d-\d\d \d\d:\d\d\.$")))
COMMENT_OPEN = re.compile(r"<!--")
CLOSED = re.compile(r"<!--.*?-->", re.S)


def _split(line):
    """(text before the first `<!--`, the rest of the logical line from it on). The rest is what sheaf or the
    person added to the line: threads, and whatever follows them. It is kept as it is."""
    at = line.find("<!--")
    return (line, "") if at < 0 else (line[:at], line[at:])


def _heads(block):
    """The text of each logical line of a block before any thread on it: what AgentView wrote, when the block is its own."""
    return [_split(l)[0].rstrip("\n") for l in _logical(block) if l.strip()]


def _text(line):
    """(head, whole): the line before its first `<!--`, and the line with every closed thread taken out. They differ
    when sheaf put a thread in the middle of the line, after the words it quotes; `whole` is then the line as
    AgentView wrote it. With a comment left open, `whole` is the head."""
    head = _split(line)[0].rstrip("\n")
    bare = CLOSED.sub("", line).rstrip("\n")
    return head, (head if "<!--" in bare else bare)


def _kinds(logical, own=None, tails=None):
    """The kind of each logical line of a block, as a tuple: `("task",)`, `("rec",)`, `("pin",)`, `("by",)`,
    `("ships",)` (the header), `("bullet", text, n)` (the n-th time this bullet is there) or `("result",)` for what
    AgentView wrote, None for what it did not. A kind counts once.

    `own` is the record of what AgentView wrote last (a Counter of line texts): with it, a line is AgentView's only
    when its text is in the record, whatever shape it has, and a bullet counts wherever it stands under the header.
    Without it (an item written before the record existed) the exact shapes decide. A line in the record that has
    no shape is `("own", text, n)`. `tails`, when given, gets one entry per line: None for a line whose text before its
    first thread is what is AgentView's, else the words the person typed after what AgentView wrote, for a line that
    has a thread in its middle (they are `""` when it holds nothing of the person's). The line, threads taken out,
    is then AgentView's line, longest recorded one first, and the thread's place on it does not matter."""
    out, seen, in_ships = [], set(), False
    own = Counter(own) if own is not None else None
    for i, line in enumerate(logical):
        head, whole = _text(line)
        mid = None
        if own is not None and whole != head and own[head] <= 0:
            if own[whole] > 0:
                mid = ""
            else:
                got = max((r for r in own if own[r] > 0 and r.strip() and len(r) >= len(head) and whole.startswith(r)), key=len, default=None)
                if got is not None:
                    mid = whole[len(got):]
                    whole = got
        if mid is not None:
            head = whole
        ours = own is None or own[head] > 0
        if i == 0:
            kind = ("task",)
        elif not ours:
            kind = None
        elif head == SHIPS_HEADER:
            kind = ("ships",)
        elif head.startswith("    ") and head.strip() and (own is not None or in_ships):
            kind = ("bullet", head, 1)
            while kind in seen:                                  # the same bullet twice: the second is its own kind
                kind = ("bullet", head, kind[2] + 1)
        elif RESULT.match(head):
            kind = ("result",)
        else:
            kind = next(((k,) for k, shape in OWN_LINES if shape.match(head)), None)
            if kind is None and own is not None and head.strip():
                kind = ("own", head, 1)
                while kind in seen:
                    kind = ("own", head, kind[2] + 1)
        if kind in seen:
            kind = None
        elif kind:
            seen.add(kind)
        if kind and own is not None and i:
            own[head] -= 1
        in_ships = kind == ("ships",) or (in_ships and kind is not None and kind[0] == "bullet")
        out.append(kind)
        if tails is not None:
            tails.append(mid if kind else None)
    return out


def _logical(block):
    """The block as logical lines: a physical line plus the ones after it that start inside a comment it opened,
    so a thread sheaf wrote across several lines stays one piece with the line it is about."""
    out = []
    for _, line, inside in _walk(block):
        if inside and out:
            out[-1] += line
        else:
            out.append(line)
    return out


QUOTE = re.compile(r'<!--\s*(?:sheaf|rd)-comment\b[^\n]*?\bquote="([^"\n]*)"')
ORPHAN = re.compile(r"<!--\s*(?:sheaf|rd)-comment\b[^\n]*?\borphan=1\b")


def _anchored(head, comment):
    """Whether sheaf can still anchor `comment` on a line whose text is `head`: the passage it quotes is the words just
    before it (SPEC 5.2; `edit._occurrence` reads it so), compared without spaces. A thread that is not sheaf's, or
    has no quote, or is already an orphan, has nothing to anchor."""
    quote = QUOTE.match(comment)
    if not quote or ORPHAN.match(comment):
        return True
    before = re.sub(r"^\s*(?:[-*+] (?:\[[ xX]\] )?)?", "", head)
    before = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", before)             # sheaf quotes the words shown: a link's text, not its address
    bare = lambda t: "".join(re.sub(r"[`*_~\\]", "", html.unescape(t)).split())     # without the marks of bold, italic, code; a plain `_` is lost too, on both sides
    return bare(before).endswith(bare(quote.group(1)))


def _orphaned(comment):
    """The thread as sheaf writes one whose passage is gone: `orphan=1` before the quote, on a line of its own."""
    if ORPHAN.match(comment):
        return comment
    return re.sub(r"(\bquote=\")", r"orphan=1 \1", comment, count=1)


def _settle_threads(rest, old_head, new_head):
    """(what stays on the line, the threads that no longer fit it as orphans). A line whose words did not change keeps
    all it had; on a changed line a thread stays only where its quote still ends the words."""
    if old_head == new_head:
        return rest, []
    kept, lost, at = "", [], 0
    for m in CLOSED.finditer(rest):
        kept += rest[at:m.start()]
        if _anchored(new_head, m.group(0)):
            kept += m.group(0)
        else:
            lost.append(_orphaned(m.group(0)))
        at = m.end()
    return kept + rest[at:], lost


def carry(old, new, own=None):
    """`new`, the block AgentView writes now, with what `old`, the block on the page, holds that AgentView did not
    write: the threads sheaf keeps on its lines, and the lines the person wrote. Only AgentView's own lines are
    replaced: the lines in `own`, the record of what it wrote last, or, with no record, the exact shapes. A thread,
    and the text after it, goes on the new line of the same kind when its quoted words still end that line; else
    the thread goes on a line of its own as an orphan, as sheaf writes one whose text is gone, and so does one whose
    kind is not in the new block (or that is never closed). A line of the person's stays after the line of the kind
    it followed."""
    if not new.endswith("\n"):
        new += "\n"
    new_lines = _logical(new)
    new_kinds = _kinds(new_lines, Counter(_heads(new)))
    ships = ("ships",)
    home = lambda k: k if k in new_kinds else (ships if k[0] == "bullet" and ships in new_kinds else None)
    ships_end = next((k for k in reversed(new_kinds) if k and k[0] in ("ships", "bullet")), None)      # a line that followed a bullet now gone goes after the last one: the list stays whole
    after = lambda k: k if k in new_kinds else (ships_end if k[0] == "bullet" else None)
    marks, theirs, orphans, blanks, last = {}, {}, [], [], ("task",)
    old_lines = _logical(old)
    tails = []
    for (kind, line), mid in zip(zip(_kinds(old_lines, own, tails), old_lines), tails):
        if kind is None:
            if not line.strip():
                blanks.append(line)                              # kept only when a line of the person's comes after it
                continue
            (theirs.setdefault(after(last), []) if after(last) else orphans).extend(blanks + [line])
            blanks = []
            continue
        last = kind
        head, rest = _split(line)
        rest = rest.rstrip("\n")
        if not rest:
            continue
        if mid is not None:                                      # a thread in the middle of our line: the threads stay, and the person's words after ours
            head = _text(line)[1][:len(_text(line)[1]) - len(mid)]
            rest = "".join(m.group(0) for m in CLOSED.finditer(rest))
            if mid.strip():                                      # the person's words stay as a line of theirs after ours, so the line is ours again next time
                (theirs.setdefault(after(kind), []) if after(kind) else orphans).append("  " + mid.strip() + "\n")
        if CLOSED.sub("", rest).count("<!--") or not home(kind):   # a thread left open would swallow the lines below it
            orphans.append("  " + CLOSED.sub(lambda m: _orphaned(m.group(0)), rest) + "\n")   # its line is gone: nothing is left to quote
        else:
            marks.setdefault(home(kind), []).append((head.rstrip("\n"), rest, line.rstrip("\n") if mid == "" else None))
    out = []
    for kind, line in zip(new_kinds, new_lines):
        head = _split(line)[0].rstrip("\n")
        on_line = ""
        for old_head, rest, original in marks.pop(kind, []):
            if original and old_head == head and not on_line:
                head, on_line = original, ""                        # the line did not change: it stands as it was, thread where it was
                continue
            kept, lost = _settle_threads(rest, old_head, head)
            on_line += kept
            orphans.extend("  " + t + "\n" for t in lost)
        out.append(head + on_line + "\n")
        out.extend(theirs.pop(kind, []))
    return "".join(l if l.endswith("\n") else l + "\n" for l in out + orphans)


# What AgentView wrote, as it wrote it: for each item (its key, lower-cased unless it is an Install item), the text of
# the lines of its last block (`lines`) and of the block before it (`prev`, for a write that did not finish), and the
# result lines of the presses since. A line the person wrote is never in it, whatever shape it has. It lives beside
# the desk file, and only `edit` reads and writes it, under the desk lock.
RECORD = ".merge-desk.own.json"


def _slot(key):
    return key if key.startswith("install:") else key.lower()


def _own(record, key):
    """The Counter of line texts that are AgentView's for `key`, or None when there is no record of it."""
    got = (record or {}).get(_slot(key))
    return None if got is None else Counter(got["lines"]) | Counter(got["prev"])


def _record_block(record, key, block):
    if record is None:
        return
    heads, was = _heads(block), record.get(_slot(key))
    if was is None or was["lines"] != heads:
        record[_slot(key)] = {"lines": heads, "prev": was["lines"] if was else []}


def put(text, key, block, section="merge", record=None):
    """`text` with the item `key` set to `block`: replaced where it stands, else
    added at the end of its section. A section that is not there yet is made. `record` is what AgentView wrote last
    (`edit` gives it); it is brought up to date with `block`."""
    record = getattr(_held, "record", None) if record is None else record
    if not block.endswith("\n"):
        block += "\n"
    for k, start, end in _spans(text):
        if k == key or (k.lower() == key.lower() and not key.startswith("install:")):   # GitHub's names are not case-sensitive, a tool's are
            kept = carry(text[start:end], block, _own(record, k))
            _record_block(record, k, block)
            return text[:start] + kept + text[end:]
    _record_block(record, key, block)
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


def drop(text, key, record=None):
    record = getattr(_held, "record", None) if record is None else record
    for k, start, end in _spans(text):
        if k == key:
            if record is not None:
                record.pop(_slot(k), None)
            return text[:start] + text[end:]
    return text


RESULT = re.compile(r"^  - (?:(?:Already merged|Merged)(?: as [0-9a-f]{7})? at \d\d:\d\d|Not merged: .*"
                    r"|(?:Already installed|Installed) as [0-9a-f]{7} at \d\d:\d\d.*|Not installed: .*)$")


def settle(text, key, result, untick=False, pinned=None, record=None):
    """`text` with the result of a press written as the last sub-line of item `key` (the
    last result sub-line of an earlier press is replaced), and its box unticked when `untick`; with `pinned`, only an item still pinned at that commit. Text with
    no such item comes back as it was. A result line is replaced only if AgentView wrote it (the record says so, else
    its shape); the new one goes in the record."""
    record = getattr(_held, "record", None) if record is None else record
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
        own = _own(record, k)
        if RESULT.match(kept[at]) and (own is None or own[kept[at]] > 0):
            del kept[at]
        if record is not None and _slot(k) in record:
            entry = record[_slot(k)]
            entry["lines"] = [l for l in entry["lines"] if not RESULT.match(l)] + ["  - " + result]
        if untick and kept[0][3] in "xX":
            kept[0] = kept[0][:3] + " " + kept[0][4:]
        return text[:start] + "\n".join(kept + ["  - " + result]) + tail + text[end:]
    return text


def _load_record(file):
    """The record beside `file`, or {} when there is none or it cannot be read: every item then falls back to the shapes."""
    try:
        got = json.loads((file.parent / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ok = isinstance(got, dict) and all(isinstance(v, dict) and all(isinstance(v.get(f), list) and all(isinstance(x, str) for x in v[f])
                                                                    for f in ("lines", "prev")) for v in got.values())
    return got if ok else {}


def edit(change, file=None):
    """Read the file fresh under the lock, apply `change(text) -> text`, write it whole
    or not at all. Returns what `change` returned about it (the new text). `put`, `drop` and `settle` inside
    `change` read and update the record of what AgentView wrote; it is saved beside the file, before the file."""
    with locked(file) as f:
        stored = _load_record(f)
        mine = getattr(_held, "record", None)
        try:
            # Sheaf writes this file too, with a lock of its own: a tick or a comment that lands
            # between our read and our replace would be lost, so look again just before replacing.
            for _ in range(5):
                before = _read(f)
                _held.record = record = copy.deepcopy(stored)
                after = change(before)
                if after != before and _read(f) != before:
                    continue
                if record != stored and not lines.write_atomic(f.parent / RECORD, json.dumps(record)):
                    raise OSError(f"could not write {f.parent / RECORD}")
                if after == before:
                    return after
                if not lines.write_atomic(f, after):
                    raise OSError(f"could not write {f}")
                return after
            raise OSError(f"{f} keeps changing under us; try again")
        finally:
            _held.record = mine


def put_item(key, block, section="merge", file=None):
    return edit(lambda t: put(t, key, block, section), file)


def drop_item(key, file=None):
    return edit(lambda t: drop(t, key), file)
