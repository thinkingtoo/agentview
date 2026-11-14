# 28: An unterminated comment hides later items; leftovers of ticket 27's review

**What to fix:** findings of the Sonnet review of ticket 27 (/home/tiroir/Projects/agentview-wt/arvid-27-sonnet-1.md) that ticket 27 left. Each needs a test first. Only a hand edit makes an unterminated comment (sheaf closes its own), and b3 dates from before 27.
- (class b, b3) A `<!--` the person left open on one of our lines swallows everything below it up to the end of the page: the items below stay hidden, and `carry` appends its closing ` -->` after all that was swallowed, so they stay hidden. A later hand-over of such a hidden item appends a live duplicate of it.
- (class c, c1) `_prev_stands` takes a person's copy of an old pin line for ours when the person also edited our current pin line; the copy is then dropped at the next hand-over.
- (class c, c2) `prev` in the record grows without bound while writes to the page keep failing.
- (class c, c3) A CRLF page ends with mixed line endings after a hand-over (our new lines are LF). Also `adopt`'s `done` and `skipped` lists are filled twice when `edit` retries (this one predates ticket 27).
- (class b, Sonnet round 2, predates 27) `TASK` ends in `(?::|$)` and `$` does not match before a `\r`: a colon-less task line on a CRLF page (`- [ ] Merge a/b#1\r\n`, `- [ ] Install foo\r\n`) is not read as an item. Check first whether AgentView writes a task line without a colon.
- (class b, Sonnet review of ticket 23, /home/tiroir/Projects/agentview-wt/rune-23-sonnet-1.md findings 2 and 7, predate 23) A `<!--` left open on the task line (`- [ ] Deploy ... <!-- oops`): the block lands after the swallowed text, the page ends with an open comment, and a second hand-over appends the block again. A `<!--` left open on the result line: `settle` writes the new result under the next item.
- (class c, same review, finding 4) On a CRLF page the ` -->` that `carry` adds leaves a lone `\r` (`- [ ] x\r -->`); belongs with c3.
- (class c, same review, finding 6) `settle` does not replace a result line with a thread in its middle (`Not merged: CI<thread> is red`): two result lines result.
- (class c, cosmetic, same review, findings 1 and 5) After settling a result line that carries a thread, a second settle with the same result moves the result below the orphan thread (stable from the third on). A thread placed after the person's words (`Merge it.<c2> and fine<c3>`) detaches from its passage: c3's quote is "and fine", which moved to its own line (the docstring of `_without_words` says it so).

**Blocked by:** 27, 23 (same deskfile.py carry code: one at a time, Tarek)

**Status:** open

- [ ] An unterminated comment on one of our lines does not hide the items below it after a hand-over, and a later hand-over of such an item does not append a duplicate (test)
- [ ] A copy of an old pin line stays the person's when they also edited our current pin line (test)
- [ ] `prev` stays bounded while writes keep failing (test)
- [ ] A CRLF page keeps one kind of line end after a hand-over (test)
- [ ] A colon-less task line on a CRLF page is still an item, or AgentView never writes one (test or the line why)
- [ ] `adopt` returns each key once when `edit` retries (test)
- [ ] An unterminated comment on the task line or the result line is not left open by a hand-over or a settle, and a second hand-over does not append the block again (test)
- [ ] The ` -->` `carry` adds on a CRLF page leaves no lone `\r` (test, with c3)
- [ ] `settle` replaces a result line with a thread in its middle (test)
- [ ] A second settle with the same result keeps the result where it was; a thread after the person's words stays with them, or the docstring says why not (test or the line why)
