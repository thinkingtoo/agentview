"""The merge desk as a table: one row per item, and a tick from the table's button.

The page stays the one place a press is decided. `rows()` reads it through `deskfile.items()`; `tick()`
writes the same `[x]` the person would type on the sheaf page, under the desk's own lock, and the watcher
presses it on its next poll. A tick is refused when the item is not on the page once, is already ticked,
or was handed over again at another commit since the table read it.
"""
import re

import deskfile
import deskring

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
