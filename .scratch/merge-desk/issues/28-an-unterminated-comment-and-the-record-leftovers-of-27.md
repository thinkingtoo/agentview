# 28: An unterminated comment hides later items; leftovers of ticket 27's review

**What to fix:** findings of the Sonnet review of ticket 27 (/home/tiroir/Projects/agentview-wt/arvid-27-sonnet-1.md) that ticket 27 left. Each needs a test first. Only a hand edit makes an unterminated comment (sheaf closes its own), and b3 dates from before 27.
- (class b, b3) A `<!--` the person left open on one of our lines swallows everything below it up to the end of the page: the items below stay hidden, and `carry` appends its closing ` -->` after all that was swallowed, so they stay hidden. A later hand-over of such a hidden item appends a live duplicate of it.
- (class c, c1) `_prev_stands` takes a person's copy of an old pin line for ours when the person also edited our current pin line; the copy is then dropped at the next hand-over.
- (class c, c2) `prev` in the record grows without bound while writes to the page keep failing.
- (class c, c3) A CRLF page ends with mixed line endings after a hand-over (our new lines are LF). Also `adopt`'s `done` and `skipped` lists are filled twice when `edit` retries (this one predates ticket 27).

**Blocked by:** 27

**Status:** open

- [ ] An unterminated comment on one of our lines does not hide the items below it after a hand-over, and a later hand-over of such an item does not append a duplicate (test)
- [ ] A copy of an old pin line stays the person's when they also edited our current pin line (test)
- [ ] `prev` stays bounded while writes keep failing (test)
- [ ] A CRLF page keeps one kind of line end after a hand-over (test)
- [ ] `adopt` returns each key once when `edit` retries (test)
