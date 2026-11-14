# 32: Settle and put leftovers of the shapes (deskfile.py, classes b and c)

**What to build:** the class b and c findings of the Codex and Sonnet reviews of tickets 19, 27 and 28 that tickets 31 does not cover. Each needs a red test first. Same file as 31, so one at a time.

Reviews and heads:
- 19: /home/tiroir/Projects/agentview-wt/nuno-19-codex-6.md and nuno-19-sonnet-r1.md, head 5059517.
- 27: /home/tiroir/Projects/agentview-wt/arvid-27-sonnet-r1.md, head 6501f8b.
- 28: /home/tiroir/Projects/agentview-wt/kofi-28-sonnet-r1.md, head 3a2b72f.

- (class b, Codex 19b, `deskfile.py:529`) `settle` skips only single-line standalone comments (`re.fullmatch(r"\s*<!--.*-->\s*", ...)`) when it looks for the previous result. A result followed by a normal multiline sheaf thread is not found, so another press appends the new result without removing the old one, and the record forgets the stale one.
- (class b, Sonnet 19, `~559`, with 543-551 and 570) `edit` reads a corrupt or unreadable record as `{}`, and the next `put` overwrites the record file with only that item's entry. That defeats `adopt`'s refusal (625-626): other items lose their record, presses are refused and a re-hand-over duplicates lines.
- (class b, Sonnet 19, `deskfile.py:602` against 167 and 285) `_adoptable` and `_kinds` need `head == SHIPS_HEADER` exactly while `ships_of` accepts `head.rstrip()`. A What ships header with a trailing space (for example before a thread) drops the header and all its bullets from the adopted record, so a re-hand-over duplicates the ships list. Reproduced by the reviewer.
- (class b, Sonnet 27 F1, `624-640`) On a CRLF page with a blank line after the item, `settle` neither replaces the old result nor places the new one right: `block.rstrip("\n")` leaves a lone `"\r"` as the last element, so the walk-back stops there. The same page with LF works.
- (class b, Sonnet 27 F2, `585-586`) `put` of a new item into a CRLF section lands after the blank line before the next heading, so the previous item's block ends in a blank line and F1 hits it.
- (class b, Sonnet 27 F3, `451-457` against `474-476`) `carry` closes an unterminated comment only on lines AgentView recognises as its own. On a person's line, or one with a space before `<!--` (`r <!-- oops`), the open comment is copied as it is and the new lines go inside it; `parse` then gives pin `''` and the press is refused. Without the space (`r<!-- oops`) it closes right.
- (class c, Sonnet 19) `adopt`: the readability check at 625 is outside the lock; the docstring of `settle` (515-517) promises a shape fallback that the code (532) does not give: with no record, or a thread on the result line, an old result is not replaced and a second one is appended.
- (class c, Sonnet 28) An open comment on a task line, closed only by a later thread's `-->` with no other item or heading between, is judged closed (`_open_at`, 167): `<!-- oops` stays on the task line; if sheaf later deletes the thread, the next hand-over closes it.
- (class c, Sonnet 28, `settle` ~722) When the person left `<!--` open on the result line, `_unhidden` closes it; the old result then no longer matches the record, so it is kept above the new one: two result lines (`Not merged: CI is red <!-- oops -->`, then `Merged at 12:00`).
- (class c, Sonnet 28, pre-existing, ~718) `settle` writes a second result line when a person's line follows the result line (after a blank line); the `trailing` loop handles blank lines only.
- (class c, Sonnet 27 F5, `502` and `640`) Rewritten lines and the result line are written with a bare `\n` on a CRLF page: mixed line endings.
- (class c, Sonnet 27 F6, `760-763`) `adopt`: case-duplicate keys under an existing record entry hit a plain `continue` and are not reported.

**Blocked by:** 31 (Waits on: 31; same deskfile.py)

**Status:** ready-for-agent

## Acceptance criteria
- [ ] `settle` replaces a result that is followed by a multiline thread and keeps the record's ownership of it (red test)
- [ ] A corrupt record file is not overwritten by `put`; the other items keep their entries and the press says why it refused (red test, as `adopt` refuses)
- [ ] A What ships header with a trailing space is adopted with its bullets, and a re-hand-over does not duplicate them (red test)
- [ ] `settle` on a CRLF page with a blank line after the item replaces the old result and puts the new one above the blank line (red test)
- [ ] `put` of a new item into a CRLF section lands right under the last item, not after the blank line before the next heading (red test)
- [ ] `carry` closes an open comment on a person's line and on one with a space before `<!--` (red test for both)
- [ ] With no record, or a thread on the result line, `settle` replaces the old result as its docstring says, or the docstring says what it does (test or the line why)
- [ ] An open comment on a task line closed only by a later thread's `-->` is closed after the next hand-over, and is not left to reopen when sheaf deletes the thread (red test)
- [ ] Class c: two result lines after `_unhidden` closes a left-open comment on the result line become one (test, or the line why not)
- [ ] Class c: a CRLF page keeps one kind of line end for rewritten lines and the result line; `adopt` reports case-duplicate keys under an existing entry (tests)
- [ ] Each fix is red on its review's head, green after, with the commands and results in the report
