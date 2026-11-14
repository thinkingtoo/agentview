# 23: Several threads on one line keep their order, and only sheaf's threads are marked orphan

**What to fix:** class b/c left by ticket 19 (Nuno's Sonnet round 3, /home/tiroir/Projects/agentview-wt/nuno-19-sonnet-3.md findings 3-4) plus his follow-ups:
- Several threads plus the person's words on one AgentView line come back reordered after a re-hand-over.
- `_orphaned` also edits HTML comments that are not sheaf threads.
- An unclosed `<!--` in a person's line swallows the lines after it (from ticket 16).
- settle does not replace a result line that carries a thread.
- GLOSSARY lacks "record" (.merge-desk.own.json) and "orphan".

**Blocked by:** 19, 27 (same deskfile.py carry code: one at a time, Tarek)

**Claimed by:** Rune 2026-11-14 16:17

**Status:** in-progress

- [x] Two threads and the person's words on one line keep their order across two re-hand-overs (test): tests/test_desk.py ThreadsOnOneLine.test_two_threads_and_the_persons_words_on_one_line_keep_their_order_across_two_hand_overs, red on f4866b0, passes at 21658f4 (branch rune/23)
- [x] A non-sheaf HTML comment is never marked orphan (test): ThreadsOnOneLine.test_a_comment_that_is_not_a_sheaf_thread_is_never_marked_orphan, red before, passes at 21658f4
- [x] An unclosed `<!--` in a person's line leaves the following items intact (test): ThreadsOnOneLine.test_an_unclosed_comment_in_a_persons_line_leaves_the_following_items_intact, red before, passes at 21658f4
- [x] GLOSSARY has Record and Orphan: GLOSSARY.md already has 'Desk record' (the .merge-desk.own.json) and 'Orphan (desk)' on origin/dev; no edit needed
