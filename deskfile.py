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

TASK = re.compile(r"^- \[([ xX])\] (?:(?:Merge|Deploy) ([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+)|Install ([^\s:]+))(?::|\s*$)")
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


def _open_at(text):
    """The offset of the `<!--` that opens a comment the person left open, or None when every comment is closed. That
    is the comment still open at the end of `text`, or one that a sheaf thread opens inside of, after a line that is an
    item or a heading, before the `-->` that closes it: the first was never closed and the thread's `-->` only ended
    it. Any other comment, one that holds a `<!--` of its own or a list line, is the person's note and stays: so is one
    that has its own `-->` after the thread's (a stray arrow with no opener left): the person closed it, the thread
    only sits inside the note."""
    marks = list(re.finditer(r"<!--|-->", text))

    def closed_after(n):
        """Whether an arrow with no opener left stands after mark `n`: the comment the thread sits in was closed by its own."""
        depth = 0
        for m in marks[n + 1:]:
            if m.group(0) == "<!--":
                depth += 1
            elif not depth:
                return True
            else:
                depth -= 1
        return False
    inside, at, broken = False, None, False
    for n, m in enumerate(marks):
        if m.group(0) == "<!--":
            if not inside:
                at = m.start()
            elif THREAD.match(text, m.start()) and any(TASK.match(l) or HEADING.match(l) for l in text[at:m.start()].split("\n")[1:]):
                broken = True
            inside = True
        else:
            if inside and broken and not closed_after(n):
                return at
            inside = broken = False
    return at if inside else None


def _unhidden(text, key):
    """`text` with a comment the person left open inside the item `key` closed,
    so the lines below it are lines again: an open comment swallows the rest of the page, the items below it with
    it. The comment is closed before the next task line or heading, so what the person typed in it stays in it. Only a
    comment that hides `key` or sits inside its block is closed, one at a time, and none beyond it. `text`
    as it was when it holds no such comment, or when closing them does not bring `key` into view."""
    here, found, last = text, False, None
    for _ in range(50):
        at = _open_at(here)
        if at is None or at == last:
            break
        last = at
        spans = [(s, e) for k, s, e in _spans(here) if k == key or (k.lower() == key.lower() and not key.startswith("install:"))]
        if spans and at >= spans[0][1]:
            break
        end = len(here)
        for offset, line, _ in _walk(here):
            if offset > at and (TASK.match(line) or HEADING.match(line)):
                end = offset                                         # the comment ends before the first line that is an item or a heading again
                break
        end -= len(here[:end]) - len(here[:end].rstrip("\r\n"))     # ... and before the line end that precedes it
        here = here[:end] + " -->" + here[end:]
        found = True
    shown = any(k == key or (k.lower() == key.lower() and not key.startswith("install:")) for k, _, _ in _spans(here))
    return here if found and shown else text


def _eol(block, page=None):
    """The line end `block` mostly has; a block with no line end at all (the last line of a page) has the page's."""
    if page is not None and "\n" not in block:
        return _eol(page)
    return "\r\n" if block.count("\r\n") * 2 > block.count("\n") else "\n"


SHIPS_HEADER = "  - What ships:"


def ships_of(block):
    """The sub-list under `What ships:` (four spaces of indent taken off), or None when the block has none. A bullet
    is what stands before the first `<!--` of its line: a thread on it, and what the person typed after the thread,
    are not part of it."""
    out, inside = None, False
    for line in _logical(block):
        head = _split(line)[0].rstrip("\r\n")
        if head.rstrip() == SHIPS_HEADER:
            out, inside = [], True
        elif inside and head.startswith("    ") and head.strip():
            out.append(head[4:].rstrip())
        elif inside and not head.strip() and "<!--" in line:
            continue                                    # a comment on a line of its own does not end the list
        elif inside:
            inside = False
    return out


def _pin_line(block, own, orders=None):
    """The text of AgentView's `Pinned commit:` line of `block`, comments taken out, or None. With the record of what
    it wrote (`own`), that is the pin line the record lists and no other ("" when it is gone): a person's line shaped
    like it pins nothing. None when there is no record of the item: nothing is pinned then."""
    if own is None:
        return None
    logical = _logical(block)
    for kind, line in zip(_kinds(logical, own, orders=orders), logical):
        if kind == ("pin",):
            return CLOSED.sub("", line)
    return ""


def parse(text, record=None):
    """The items of `text`. `record` is what AgentView wrote last (`edit` gives it): an item is pinned by its own
    `Pinned commit:` line only (a line the person wrote or changed pins nothing). An item with no entry in it, or no
    record at all, is pinned at nothing (""), and a press on it is refused until it is handed over again."""
    found = []
    for key, start, end in _spans(text):
        block = text[start:end]
        visible = re.sub(r"<!--.*?-->", "", block, flags=re.S)              # a comment pins nothing, and orders nothing
        got = (record or {}).get(_slot(key))                                 # the pin is read from what was written last, not from the generation before it
        mine = _pin_line(block, None if got is None else Counter(got["lines"]), None if got is None else _orders(got, prev=False))
        pin, order = PINNED.search(mine or ""), AFTER.search(visible)     # an order only refuses a press, so a person's line may add one
        found.append(Item(key, block[3] in "xX", pin.group(1) if pin else "", block, int(order.group(1)) if order else 0, ships_of(block)))
    return found


def items(file=None):
    """The items on the page now, in page order. Read-only: no lock needed."""
    file = Path(file) if file else path()
    return parse(_read(file), _load_record(file))


def items_in(text):
    """The items of `text` as `parse` reads them with the record `edit` holds: for a `change` that judges the text it is given."""
    return parse(text, getattr(_held, "record", None))


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
    return [_split(l)[0].rstrip("\r\n") for l in _logical(block) if l.strip()]


def _text(line):
    """(head, whole): the line before its first `<!--`, and the line with every closed thread taken out. They differ
    when sheaf put a thread in the middle of the line, after the words it quotes; `whole` is then the line as
    AgentView wrote it. With a comment left open, `whole` is the head."""
    head = _split(line)[0].rstrip("\r\n")
    bare = CLOSED.sub("", line).rstrip("\r\n")
    return head, (head if "<!--" in bare else bare)


def _ordinals(heads):
    """For each text of `heads`, the number of the same text before it."""
    seen, out = Counter(), []
    for h in heads:
        out.append(seen[h])
        seen[h] += 1
    return out


def _orders(entry, prev=True):
    """The ordered texts a record entry holds, with the ordinal of each among identical texts of the block it was
    written for (`at`, None for a record written before ordinals were kept): `(texts, at)` for the last block, and for
    the one before it (`prev`, no ordinals)."""
    out = [(entry["lines"], entry.get("at"))]
    if prev and entry["prev"]:
        out.append((entry["prev"], None))
    return out


def _mine(heads, orders):
    """The indices of `heads` (one per logical line of a block) that are AgentView's where the same text stands more
    than once: the record's lines, in the order it wrote them, are matched in order onto the block's, so a copy of
    one that the person put out of its place is not taken for it. Among places that match as well, the one with the
    ordinal the record keeps (none: the first). A copy next to ours, with nothing between that gives the order away,
    cannot be told from ours by its text: that is the one case left to the ordinal. The best of the orders wins."""
    best = set()
    for order, at in orders:
        n, m = len(order), len(heads)
        reach = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            for j in range(m - 1, -1, -1):
                reach[i][j] = reach[i + 1][j + 1] + 1 if order[i] == heads[j] else max(reach[i + 1][j], reach[i][j + 1])
        got, i, j, ords = set(), 0, 0, _ordinals(heads)
        while i < n and j < m:
            if order[i] == heads[j] and reach[i][j] == reach[i + 1][j + 1] + 1:
                pick = j
                if at is not None and i < len(at):
                    for k in range(j, m):
                        if heads[k] == order[i] and ords[k] == at[i] and reach[i][j] == reach[i + 1][k + 1] + 1:
                            pick = k
                            break
                got.add(pick)
                i, j = i + 1, pick + 1
            elif reach[i + 1][j] >= reach[i][j + 1]:
                i += 1
            else:
                j += 1
        if len(got) > len(best):
            best = got
    return best


def _kinds(logical, own=None, tails=None, orders=None):
    """The kind of each logical line of a block, as a tuple: `("task",)`, `("rec",)`, `("pin",)`, `("by",)`,
    `("ships",)` (the header), `("bullet", text, n)` (the n-th time this bullet is there) or `("result",)` for what
    AgentView wrote, None for what it did not. A kind counts once.

    `own` is the record of what AgentView wrote last (a Counter of line texts): a line is AgentView's only when its
    text is in the record, whatever shape it has (the task line too), and a bullet counts wherever it stands under the
    header. Without it (no record of the item, or a record that cannot be read) no line is AgentView's: every kind is
    None. A line in the record that has no shape is `("own", text, n)`. `tails`, when given, gets one entry per line: None for a line whose text before its
    first thread is what is AgentView's, else the words the person typed after what AgentView wrote, for a line that
    has a thread in its middle (they are `""` when it holds nothing of the person's). The line, threads taken out,
    is then AgentView's line, longest recorded one first, and the thread's place on it does not matter.

    `orders` (`_orders`) is the record's lines in the order it wrote them: a text that stands twice in the block is
    AgentView's only at the place `_mine` gives it, so the person's copy of a line is theirs."""
    out, seen = [], set()
    if own is None:
        if tails is not None:
            tails.extend(None for _ in logical)
        return [None for _ in logical]
    own = Counter(own)
    texts = []
    for i, line in enumerate(logical):
        head = _text(line)[0]
        texts.append(re.sub(r"^(\s*- \[)[xX]\]", r"\1 ]", head, count=1) if i == 0 else head)
    twice = {h for h, n in Counter(texts).items() if n > 1 and h.strip()}
    mine = _mine(texts, orders) if orders and twice else None       # who of identical lines is ours: the record's order says
    for i, line in enumerate(logical):
        head, whole = _text(line)
        if i == 0:                                               # the box is the person's to tick: a ticked task line is still ours
            head, whole = (re.sub(r"^(\s*- \[)[xX]\]", r"\1 ]", t, count=1) for t in (head, whole))
        mid = None
        if whole != head and own[head] <= 0:
            if own[whole] > 0:
                mid = ""
            else:
                got = max((r for r in own if own[r] > 0 and r.strip() and len(r) >= len(head) and whole.startswith(r)), key=len, default=None)
                if got is not None:
                    mid = whole[len(got):]
                    whole = got
        if mid is not None:
            head = whole
        ours = own[head] > 0 and not (mine is not None and head in twice and i not in mine)      # a copy of ours that the order says is not
        if not ours:
            kind = None
        elif i == 0:
            kind = ("task",)
        elif head == SHIPS_HEADER:
            kind = ("ships",)
        elif head.startswith("    ") and head.strip():
            kind = ("bullet", head, 1)
            while kind in seen:                                  # the same bullet twice: the second is its own kind
                kind = ("bullet", head, kind[2] + 1)
        elif RESULT.match(head):
            kind = ("result",)
        else:
            kind = next(((k,) for k, shape in OWN_LINES if shape.match(head)), None)
            if kind is None and head.strip():
                kind = ("own", head, 1)
                while kind in seen:
                    kind = ("own", head, kind[2] + 1)
        if kind in seen:
            kind = None
        elif kind:
            seen.add(kind)
        if kind and i:
            own[head] -= 1
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


THREAD = re.compile(r"<!--\s*(?:sheaf|rd)-comment\b")


def _orphaned(comment):
    """The thread as sheaf writes one whose passage is gone: `orphan=1` before the quote, on a line of its own. A
    comment that is not a sheaf thread is the person's note and stays as it is."""
    if ORPHAN.match(comment) or not THREAD.match(comment):
        return comment
    return re.sub(r"(\bquote=\")", r"orphan=1 \1", comment, count=1)


def _without_words(line, mid):
    """`line` with the person's words `mid` taken out and every thread left where it stood among the words that are
    AgentView's: the threads quote those words, so they must keep following them. The words come after ours (`mid`
    is the end of the line with the threads out); a thread after them goes at the end. So a thread that quotes the person's
    words (`Merge it.<c2> and fine<c3>`: c3 quotes "and fine") no longer has them before it once they are a line of
    their own: its quote does not end our line, and sheaf will show it as an orphan when it next anchors it. The words
    cannot stay on our line (it would not be ours next time), and the thread cannot follow them (it is on our line)."""
    if not mid:
        return line.rstrip("\n")
    bare = CLOSED.sub("", line.rstrip("\r\n"))
    keep, out, at = len(bare) - len(mid), "", 0
    for m in CLOSED.finditer(line.rstrip("\r\n")):
        text = line[at:m.start()]
        out += text[:max(keep, 0)]
        keep -= len(text)
        out += m.group(0)
        at = m.end()
    return out + line[at:].rstrip("\r\n")[:max(keep, 0)]


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


def carry(old, new, own=None, orders=None, at=None):
    """`new`, the block AgentView writes now, with what `old`, the block on the page, holds that AgentView did not
    write: the threads sheaf keeps on its lines, and the lines the person wrote. Only AgentView's own lines are
    replaced: the lines in `own`, the record of what it wrote last (the task line only when it is as recorded). With
    no record (`own` is None) none is: the page's lines all stay, and the new block's lines, its task line apart,
    go in after them. A thread,
    and the text after it, goes on the new line of the same kind when its quoted words still end that line; else
    the thread goes on a line of its own as an orphan, as sheaf writes one whose text is gone, and so does one whose
    kind is not in the new block (or that is never closed). A line of the person's stays after the line of the kind
    it followed. `orders` is the record's lines in order (see `_kinds`); `at`, a list, is given what the record
    keeps of the block that comes out: for each line of `new`, how many identical lines stand before it."""
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
    task = None                                                  # the task line as the page has it, when it is the person's
    for i, ((kind, line), mid) in enumerate(zip(zip(_kinds(old_lines, own, tails, orders), old_lines), tails)):
        if i == 0 and kind is None:
            task = line if line.endswith("\n") else line + "\n"
            continue
        if kind is None:
            if not line.strip():
                blanks.append(line)                              # kept only when a line of the person's comes after it
                continue
            if "<!--" in CLOSED.sub("", line):                    # a comment of the person's left open: it and what it swallows go last, closed, so it hides none of the lines AgentView writes
                orphans.extend(blanks + [line.rstrip("\r\n") + " -->" + ("\r\n" if line.endswith("\r\n") else "\n")])
            else:
                (theirs.setdefault(after(last), []) if after(last) else orphans).extend(blanks + [line])
            blanks = []
            continue
        last = kind
        head, rest = _split(line)
        rest = rest.rstrip("\r\n")
        if not rest:
            continue
        if mid is not None:                                      # a thread in the middle of our line: the threads stay, and the person's words after ours
            head = _text(line)[1][:len(_text(line)[1]) - len(mid)]
            rest = "".join(m.group(0) for m in CLOSED.finditer(rest))
            words = mid.strip()
        elif own is not None and rest.count("<!--") and "<!--" not in CLOSED.sub("", rest):   # our line is whole, threads after it: what stands between or after them is the person's
            words = CLOSED.sub("", rest).strip()
            rest = "".join(m.group(0) for m in CLOSED.finditer(rest))
        else:
            words = ""
        if words:                                                # the person's words stay as a line of theirs after ours, so the line is ours again next time
            (theirs.setdefault(after(kind), []) if after(kind) else orphans).append("  " + words + "\n")
        if CLOSED.sub("", rest).count("<!--") or not home(kind):   # a thread left open would swallow the lines below it
            gone = CLOSED.sub(lambda m: _orphaned(m.group(0)), rest)
            orphans.append("  " + gone + (" -->" if "<!--" in CLOSED.sub("", rest) and gone.rfind("<!--") > gone.rfind("-->") else "") + "\n")   # its line is gone: nothing is left to quote; a comment never closed is closed here, or it swallows the items below
        else:
            marks.setdefault(home(kind), []).append((head.rstrip("\r\n"), rest, _without_words(line, mid) if mid is not None else None))
    out, standing = [], Counter()
    def stand(line, ours=False):
        head = _split(line)[0].rstrip("\r\n")
        if ours and at is not None and line.strip():
            at.append(standing[head])
        standing[head] += 1
    for kind, line in zip(new_kinds, new_lines):
        if kind == ("task",) and task is not None:              # the person changed it, or there is no record: it stays, key and all
            out.append(task)
            stand(new_lines[0], True)
            for t in theirs.pop(kind, []):
                out.append(t)
                stand(t)
            continue
        head = _split(line)[0].rstrip("\r\n")
        on_line = ""
        for old_head, rest, original in marks.pop(kind, []):
            if original and old_head == head and not on_line:
                head, on_line = original, ""                        # the line did not change: it stands as it was, thread where it was
                continue
            kept, lost = _settle_threads(rest, old_head, head)
            on_line += kept
            orphans.extend("  " + t + "\n" for t in lost)
        out.append(head + on_line + "\n")
        stand(head, True)
        for t in theirs.pop(kind, []):
            out.append(t)
            stand(t)
    return "".join(l if l.endswith("\n") else l + "\n" for l in out + orphans)


# What AgentView wrote, as it wrote it: for each item (its key, lower-cased unless it is an Install item), the text of
# the lines of its last block (`lines`) and of the block before it (`prev`, for a write that did not finish), and the
# result lines of the presses since. A line the person wrote is never in it, whatever shape it has. It lives beside
# the desk file, and only `edit` reads and writes it, under the desk lock.
RECORD = ".merge-desk.own.json"


def _slot(key):
    return key if key.startswith("install:") else key.lower()


def _specific(texts, other):
    """The lines of `texts` that `other` does not have (as many times over): what tells the one generation from the other."""
    return Counter(texts) - Counter(other)


def _prev_stands(entry, block):
    """Whether `block` is the generation before the record's last (a write that did not finish: the record moved on,
    the page did not). The lines of `prev` are AgentView's only then: a person's copy of an old pin line in a block of
    the last generation is theirs, however often its text stands. The page is behind when it holds all the lines only
    the earlier generation wrote, or most of them and none that only the last wrote: a person who removed two lines of
    ours and typed a copy of an old pin line has not made the page an old one, and a page that holds a line of the last
    and lacks one of the earlier is not one."""
    if not entry["prev"]:
        return False
    texts = _heads(block)
    if texts:
        texts[0] = re.sub(r"^(\s*- \[)[xX]\]", r"\1 ]", texts[0], count=1)
    known = set(entry["prev"]) | set(entry["lines"])
    pin = dict(OWN_LINES)["pin"]
    if any(t not in known and pin.match(t) for t in texts[1:]):
        return False                    # a pin line that no generation wrote: the person edited the pin of this block, it is no stale write
    earlier, last = _specific(entry["prev"], entry["lines"]), _specific(entry["lines"], entry["prev"])
    old = Counter(texts[i] for i in _mine(texts, [(entry["prev"], None)])) & earlier
    new = Counter(texts[i] for i in _mine(texts, [(entry["lines"], entry.get("at"))])) & last
    if not earlier:
        return False
    return old == earlier or (not new and 2 * sum(old.values()) > sum(earlier.values()))   # all of what only the earlier one wrote is there, or most of it and nothing only the last wrote: one copied line of it is not a page, nor is a page that holds a line of the last and lacks some of the earlier


def _own(record, key, block=None):
    """The Counter of line texts that are AgentView's for `key`, or None when there is no record of it. With `block`, the
    page's block of it, the lines of the generation before the last count only when that is the one the page holds."""
    got = (record or {}).get(_slot(key))
    if got is None:
        return None
    if block is None or _prev_stands(got, block):
        return Counter(got["lines"]) | Counter(got["prev"])
    return Counter(got["lines"])


def _record_block(record, key, block, at=None, behind=False):
    """`at` is, for each line of `block`, how many identical lines stand before it on the page it is written onto
    (`carry` gives it): the record keeps it, so a copy of a line the person puts next to ours cannot take its place
    later. Without it the block stands alone on the page: all zero. `behind`: the page still held the generation before
    the record's last (a write that did not reach it): that one stays in `prev`, and the generation that never reached the page is not added to it (`prev` is never longer than one generation), so the page is still read as ours."""
    if record is None:
        return
    heads, was = _heads(block), record.get(_slot(key))
    at = _ordinals(heads) if at is None else at
    if was is None or was["lines"] != heads or was.get("at") != at:
        prev = was["prev"] if was and behind else was["lines"] if was and was["lines"] != heads else (was["prev"] if was else [])
        record[_slot(key)] = {"lines": heads, "prev": prev, "at": at}


def put(text, key, block, section="merge", record=None):
    """`text` with the item `key` set to `block`: replaced where it stands, else
    added at the end of its section. A section that is not there yet is made. `record` is what AgentView wrote last
    (`edit` gives it); it is brought up to date with `block`."""
    record = getattr(_held, "record", None) if record is None else record
    if not block.endswith("\n"):
        block += "\n"
    text = _unhidden(text, key)
    for k, start, end in _spans(text):
        if k == key or (k.lower() == key.lower() and not key.startswith("install:")):   # GitHub's names are not case-sensitive, a tool's are
            got, at = (record or {}).get(_slot(k)), []
            behind = got is not None and _prev_stands(got, text[start:end])
            kept = carry(text[start:end], block, _own(record, k, text[start:end]), None if got is None else _orders(got), at)
            if _eol(text[start:end], text) == "\r\n":
                kept = re.sub(r"\r?\n", "\r\n", kept)                 # a CRLF block stays one kind of line end: our lines come in with LF
            _record_block(record, k, block, at if len(at) == len(_heads(block)) else None, behind)
            return text[:start] + kept + text[end:]
    _record_block(record, key, block)
    nl = _eol(text)
    if nl == "\r\n":
        block = re.sub(r"\r?\n", "\r\n", block)
    heading = SECTIONS[section]
    at = _heading_end(text, heading)
    if at is not None and not text.endswith("\n") and at == len(text):
        text += nl
        at += len(nl)
    if at is None:
        text = text.rstrip("\r\n") + nl * 2 + heading + nl
        at = len(text)
    end = next((o for o, line, inside in _walk(text) if o >= at and not inside and line.startswith("## ")),
               len(text))
    nxt = end < len(text)
    body = text[at:end]
    tail = body[len(body.rstrip("\r\n")):]          # the blank line before the next heading
    new = body.rstrip("\r\n") + (nl if body.strip() else "") + block
    return _unhidden(text[:at] + new + (tail if nxt else "") + text[end:], key)           # a comment left open above it would hide it


def _heading_end(text, heading):
    """Offset just after the heading's own line (outside any comment), or None."""
    for offset, line, inside in _walk(text):
        if not inside and line.rstrip("\r\n") == heading:
            return offset + len(line)
    return None


def drop(text, key, record=None):
    record = getattr(_held, "record", None) if record is None else record
    text = _unhidden(text, key)
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
    text = _unhidden(text, key)
    for k, start, end in _spans(text):
        if k != key:
            continue
        block = text[start:end]
        if pinned is not None and parse(block, record)[0].pinned != pinned:      # the item was handed over again meanwhile
            return text
        body = block.rstrip("\n")
        crlf = _eol(block, text) == "\r\n"
        tail = block[len(body):] or "\n"
        kept = [l.rstrip("\n") for l in _logical(body)]
        if crlf and not body.endswith("\r"):
            kept[-1] += "\r"                                            # the page's last line has no line end: it gets one now that a line follows it
        trailing = []
        while len(kept) > 1 and not kept[-1].strip():                    # blank lines after the item (a lone `\r` on a CRLF page) stay after the result
            trailing.insert(0, kept.pop())
        at = len(kept) - 1                                              # our line is always the last one, bar the person's comments after it
        while at > 0 and re.fullmatch(r"\s*<!--.*-->\s*", kept[at], re.S):
            at -= 1
        own, left, cr, put_at = _own(record, k, block), [], "\r" if crlf else "", None
        head, rest = _split(kept[at])
        whole = _text(kept[at])[1]                                       # the line with its threads out: a thread in the middle of our words does not make them another line
        if RESULT.match(whole) and own is not None and own[whole] > 0:
            del kept[at]
            put_at = at                                                  # the new result goes where the old one stood, its orphaned threads after it
            if whole == head:
                left = ["  " + CLOSED.sub(lambda m: _orphaned(m.group(0)), rest).rstrip("\r") + cr] if rest.strip() else []     # the result line is gone: what was on it stays, its threads as orphans
            else:
                left = ["  " + _orphaned(m.group(0)) + cr for m in CLOSED.finditer(rest)]                  # the words after a thread are ours: only the threads stay
        if record is not None and _slot(k) in record:
            entry = record[_slot(k)]
            entry["lines"] = [l for l in entry["lines"] if not RESULT.match(l)] + ["  - " + result]
        elif record is not None:                                          # no record of the item: the result line is the one line of it that is ours
            record[_slot(k)] = {"lines": ["  - " + result], "prev": []}
        if untick and kept[0][3] in "xX":
            kept[0] = kept[0][:3] + " " + kept[0][4:]
        fresh = ["  - " + result + cr] + left
        kept[len(kept) if put_at is None else put_at:len(kept) if put_at is None else put_at] = fresh
        return text[:start] + "\n".join(kept + trailing) + tail + text[end:]
    return text


def _load_record(file):
    """The record beside `file`, or {} when there is none or it cannot be read: every item then falls back to the shapes."""
    try:
        got = json.loads((file.parent / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ok = isinstance(got, dict) and all(isinstance(v, dict) and all(isinstance(v.get(f), list) and all(isinstance(x, str) for x in v[f])
                                                                    for f in ("lines", "prev")) for v in got.values())
    if not ok:
        return {}
    for v in got.values():                                  # `at` came with ticket 26: a record without it, or with one that is not a list of numbers, reads as before
        if "at" in v and not (isinstance(v["at"], list) and all(type(x) is int and x >= 0 for x in v["at"])):
            del v["at"]
    return got


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


def _only_results(entry):
    """Whether a record entry holds nothing but result lines: `settle` made it for an item that had no record."""
    return all(RESULT.match(l) for l in entry["lines"])


def _is_empty_record(file):
    try:
        text = file.read_text(encoding="utf-8")
        return not text.strip() or json.loads(text) == {}
    except (OSError, ValueError):
        return False


YAML = r"[A-Za-z0-9_.-]+\.ya?ml"
SHIPS_TOP = re.compile(r"    - (?:Outside GitHub: .*|Could not tell what ships: .*To go on, merge it on GitHub yourself.*"
                       r"|Fires on push to \S+: " + YAML + r"(?:, " + YAML + r")*|This pull request changes workflow files:|Commits that go out \(\d+\):)$")
SHIPS_UNDER = (("Fires on push to ", re.compile(r"      - " + YAML + r"(?::\d+: |: structure sha256:)")),
               ("Commits that go out (", re.compile(r"      - (?:[0-9a-f]{7} |and \d+ more$)")),
               ("This pull request changes workflow files:", re.compile(r"      - \.github/workflows/")))


def _ships_line_is_ours(head, parent):
    """Whether `head`, a line under `What ships:`, has a shape `deskships` writes: a bullet of its own kind, or a line
    under the bullet `parent` (the text of the last top bullet taken) of the kind that bullet has. A person's note under
    the header is neither."""
    if SHIPS_TOP.match(head):
        return True
    return any(parent.startswith(top) and shape.match(head) for top, shape in SHIPS_UNDER)


def _adoptable(block):
    """The lines of `block` AgentView wrote, judged by shape and place, or None when the block holds two lines of one
    kind (a person's copy beside ours: which is ours cannot be told). A bullet counts only inside the `What ships:` list
    and only in a shape `deskships` writes (`_ships_line_is_ours`), so a note the person typed there is not taken; the
    task line is taken with its box unticked, as AgentView wrote it."""
    out, seen, in_ships, parent = [], Counter(), False, ""
    for i, line in enumerate(_logical(block)):
        head = _split(line)[0].rstrip("\r\n")
        if i == 0:
            out.append(re.sub(r"^(\s*- \[)[xX]\]", r"\1 ]", head, count=1))
            continue
        if not head.strip():
            if "<!--" not in line:                           # a blank line ends the list, as `ships_of` reads it
                in_ships = False
            continue                                         # a thread on a line of its own ends nothing
        kind = next((k for k, shape in OWN_LINES if shape.match(head)), None)
        if head == SHIPS_HEADER:
            in_ships, parent = True, ""
            out.append(head)
        elif in_ships and head.startswith("    ") and head.strip():
            if _ships_line_is_ours(head, parent):
                out.append(head)
                if SHIPS_TOP.match(head):
                    parent = head[6:]
            elif not head.startswith("      "):
                parent = ""                                  # a note of the person's between bullets: what is nested after it is not ours
        else:
            in_ships = False
            if RESULT.match(head):
                out.append(head)
            elif kind:
                seen[kind] += 1
                out.append(head)
    return None if any(n > 1 for n in seen.values()) else out


def _adopted_at(block, lines):
    """For each of `lines` (what `_adoptable` took from `block`, in order), how many identical lines stand before it in the block."""
    heads, at, j = _heads(block), [], 0
    if heads:
        heads[0] = re.sub(r"^(\s*- \[)[xX]\]", r"\1 ]", heads[0], count=1)
    before = Counter()
    for h in heads:
        if j < len(lines) and h == lines[j]:
            at.append(before[h])
            j += 1
        before[h] += 1
    return at


def adopt(file=None):
    """One-time, by hand (`desk adopt`): for each item with no entry in the record, write the entry from the lines
    of its block that AgentView wrote (by shape and place), taking them as its own. Items that have an entry are left
    alone, so a second run changes nothing. An item with two lines of one kind is skipped: it is the person's to sort
    out. Refuses when the record file exists but cannot be read (corrupt means nothing is ours, not "start again").
    Returns (the keys adopted, the keys skipped)."""
    f = Path(file) if file else path()
    rec = f.parent / RECORD
    done, skipped = [], []

    def change(text):
        done.clear()
        skipped.clear()                                      # `edit` may run this again on a page that moved under it
        if rec.exists() and not _load_record(f) and not _is_empty_record(rec):      # looked at under the lock: nobody changes it between this and the write
            raise OSError(f"{rec} cannot be read; look at it before adopting")
        record = _held.record
        for k, start, end in _spans(text):
            if _slot(k) in record and not _only_results(record[_slot(k)]):
                if any(_slot(d) == _slot(k) for d in done):
                    skipped.append(k)                        # a second item under the same record entry (the case of its key differs): it cannot have one of its own
                continue
            lines = _adoptable(text[start:end])
            if lines is None:
                skipped.append(k)
                continue
            record[_slot(k)] = {"lines": lines, "prev": [], "at": _adopted_at(text[start:end], lines)}
            done.append(k)
        return text
    edit(change, f)
    return done, skipped


def put_item(key, block, section="merge", file=None):
    return edit(lambda t: put(t, key, block, section), file)


def drop_item(key, file=None):
    return edit(lambda t: drop(t, key), file)
