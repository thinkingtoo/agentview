"""The merge desk as a table: one row per item, and a tick from the table's button.

The page stays the one place a press is decided. `rows()` reads it through `deskfile.items()`; `tick()`
writes the same `[x]` the person would type on the sheaf page, under the desk's own lock, and the watcher
presses it on its next poll. A tick is refused when the item is not on the page once, is already ticked,
or was handed over again at another commit since the table read it.

`discard()` throws an item away: a PR is closed on GitHub with its branch deleted, and the item leaves the
page. It is for the work nobody will merge, a "don't merge" on a retired device; GitHub keeps the closed PR,
and its page offers to restore the branch.
"""
import re

import desk
import deskfile
import deskring
import deskwatch

VERDICT = re.compile(r"^  - Recommendation: (merge|don't merge|wait|found by the scan, no recommendation yet)\b\.?[ \t]*(.*)$", re.M)
DONE = re.compile(r"^  - (?:Already merged|Merged|Already installed|Installed)\b.*$", re.M)
REFUSED = re.compile(r"^  - (?:Not merged|Not installed): .*$", re.M)
WHY = 300


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _row(item):
    first = item.block.split("\n", 1)[0].rstrip("\r")
    kind = first[6:].split(" ", 1)[0]
    name = first.split(":", 1)[1].strip() if ":" in first[6:] else ""
    repo, _, number = item.key.partition("#")
    if item.key.startswith("install:"):
        repo, number = "", ""
    got = VERDICT.search(item.block)
    verdict = "none" if not got or got.group(1).startswith("found") else got.group(1)
    why = got.group(2).strip() if got else ""
    done, refused = DONE.search(item.block), REFUSED.search(item.block)
    handed = deskring._handed_at(item)
    handed_text = deskring.HANDED.search(item.block)
    if done:
        state, result = "done", done.group(0)[4:]
    elif item.ticked:
        state, result = "pressing", ""
    else:
        state, result = ("refused", refused.group(0)[4:]) if refused else ("waiting", "")
    return {"key": item.key, "kind": kind, "repo": repo, "number": int(number) if number else None, "name": name,
            "verdict": verdict, "why": why if len(why) <= WHY else why[:WHY - 1] + "…",
            "handed": handed_text.group(1) if handed_text else "", "handed_at": handed,
            "pinned": item.pinned, "state": state, "result": result}


def rows(file=None):
    """One dict per item on the page, in page order."""
    return [_row(i) for i in deskfile.items(file)]


def tick(key, pinned, file=None):
    """Tick the box of item `key`, if it is still on the page once, unticked and pinned at `pinned`."""
    def change(text):
        spans = [s for s in deskfile._spans(text) if deskfile.same_key(s[0], key)]
        if not spans:
            raise Refused(404, f"{key} is no longer on the desk")
        if len(spans) > 1:
            raise Refused(409, f"{key} is on the desk twice; fix the page first")
        item = next(i for i in deskfile.items_in(text) if deskfile.same_key(i.key, key))
        if item.ticked:
            raise Refused(409, f"{key} is already ticked")
        if item.pinned != pinned:
            raise Refused(409, f"{key} was handed over again since this table was read; reload it")
        _, start, _ = spans[0]
        return text[:start + 3] + "x" + text[start + 4:]
    deskfile.edit(change, file)


def _check(key, pinned, file=None):
    """The item `key` as the page has it now, refused as `tick` refuses it."""
    found = [i for i in deskfile.items(file) if deskfile.same_key(i.key, key)]
    if not found:
        raise Refused(404, f"{key} is no longer on the desk")
    if len(found) > 1:
        raise Refused(409, f"{key} is on the desk twice; fix the page first")
    if found[0].ticked:
        raise Refused(409, f"{key} is ticked: the watcher is pressing it")
    if found[0].pinned != pinned:
        raise Refused(409, f"{key} was handed over again since this table was read; reload it")
    return found[0]


def discard(key, pinned, gh=deskwatch.gh, file=None):
    """Close the PR of item `key` (branch deleted) unless GitHub has it closed already, then take the item off the page."""
    _check(key, pinned, file)
    if not key.startswith("install:"):
        repo, _, n = key.partition("#")
        code, out = gh("pr", "view", n, "-R", repo, "--json", "state", "-q", ".state")
        if code:
            raise Refused(502, f"GitHub could not be asked about {key}: {desk.flatten(out, 160)}")
        if out == "OPEN":
            code, out = gh("pr", "close", n, "-R", repo, "--delete-branch",
                           "--comment", "Discarded from the merge desk: not to be merged.")
            if code:
                raise Refused(502, f"GitHub did not close {key}: {desk.flatten(out, 160)}")
    with deskfile.locked(file):
        _check(key, pinned, file)
        deskfile.drop_item(key, file)
        desk.log("withdrawn", key, discarded=True)
