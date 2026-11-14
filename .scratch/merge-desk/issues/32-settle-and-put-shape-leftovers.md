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

Findings of the Codex reviews of 26 and 24 (Boris, 2026-11-14), checked at the merged head and at origin/dev 63d026b:
- (class b, Codex on 26, /home/tiroir/Projects/agentview-wt/boris-26-codex-1.md, `deskfile.py:~320`, VERIFIED at 0e20d0d and on dev) `twice` is built from `_text(line)[0]`, the text before the first `<!--`. When sheaf has put a thread in the middle of our pin line and the person pastes a plain copy of it, the two texts differ, so `_mine()` is never asked and the copy is taken for ours. The next hand-over deletes the person's copy and keeps our stale threaded line. Repro: `put` a block (pin a), put a thread after "Pinned" in our pin line (`Pinned<!-- sheaf-comment id=c1 by="T" at=2026-11-14T01:00 status=open quote="Pinned"\nhi\n--> commit: ...`), paste the plain pin line above the Recommendation, `put` again with pin b: the plain copy is gone, the threaded line with pin a stays.
- (class c, Codex on 24, /home/tiroir/Projects/agentview-wt/boris-24-codex-1.md, `tests/test_desk_relay.py:362-369`, VERIFIED at 226d83a and on dev) `TheHubsOps.SHEAF_PYTHON` hard-codes `~/.local/share/uv/tools/sheafmd/bin/python` and skips silently when sheaf is installed elsewhere, so the guard on `COMMENT_OPS` can pass without running.
Findings of Nuno's Sonnet round 2 on 31 (/home/tiroir/Projects/agentview-wt/nuno-31-sonnet-2.md, e68b723...b87a1c1, all three fail on the safe side: text is kept or an item stays hidden):
- (class b) `_open_at` (31c): any unmatched `-->` later on the page (a person's `see A --> B`) makes a real left-open comment read as a closed note; the hidden item stays hidden and `put` adds a second copy. Nothing is deleted.
- (class b) `_adoptable` (31a): a person's line with exactly one of deskships' shapes (`    - Outside GitHub: my text`) is still adopted, which text alone cannot tell apart. Find a way to tell them apart, or write it down as a known limit, as ticket 33 did.
- (class c) `_prev_stands` (31b): a page one write behind whose Recommendation and Handed-over lines were removed is no longer judged behind, and the old pin stays as the person's.

- (design, Tarek, from /home/tiroir/Projects/agentview-wt/gaspar-33/handoff-gaspar-2026-11-14.md) `deskscan.over()` (ticket 33, 0f5a61b) reads an item's own result lines through private deskfile names (`_kinds`, `_logical`, `_own`, `_orders`, `_prev_stands`, `_slot`, `_text`, `_held.record`): deskfile gets one public function that returns them.

**Blocked by:** 31 (Waits on: 31; same deskfile.py)

**Claimed by:** Rumi 2026-11-14 20:49 (from Boris, by Tarek)

**Status:** done

## Acceptance criteria
- [x] `settle` replaces a result that is followed by a multiline thread and keeps the record's ownership of it (red test)
  - Evidence: already green on the starting head (ticket 28 fixed it): SettleAndPutShapes.test_settle_replaces_a_result_that_a_multiline_thread_follows…; settle now finds the old result by `_kinds` (cfe9848)
- [x] A corrupt record file is not overwritten by `put`; the other items keep their entries and the press says why it refused (red test, as `adopt` refuses)
  - Evidence: red then green: test_a_corrupt_record_is_not_overwritten_by_a_hand_over… (put/drop raise `cannot be read`; settle writes the page, leaves the record: test_a_press_still_writes…). The old test that expected the overwrite was changed to the new contract
- [x] A What ships header with a trailing space is adopted with its bullets, and a re-hand-over does not duplicate them (red test)
  - Evidence: red then green: test_a_header_with_a_trailing_space_is_adopted… (`_head`)
- [x] `settle` on a CRLF page with a blank line after the item replaces the old result and puts the new one above the blank line (red test)
  - Evidence: already green on the starting head: test_settle_on_a_crlf_page_with_a_blank_line…
- [x] `put` of a new item into a CRLF section lands right under the last item, not after the blank line before the next heading (red test)
  - Evidence: red then green (a doubled blank line before the next heading, LF and CRLF): test_put_of_a_new_item_into_a_crlf_section…
- [x] `carry` closes an open comment on a person's line and on one with a space before `<!--` (red test for both)
  - Evidence: already green on the starting head (open comments are closed on the person's lines): test_carry_closes_an_open_comment… three shapes
- [x] With no record, or a thread on the result line, `settle` replaces the old result as its docstring says, or the docstring says what it does (test or the line why)
  - Evidence: docstring now says it; test_settle_replaces_a_result_with_a_thread_in_its_middle_and_says_so_without_a_record
- [x] An open comment on a task line closed only by a later thread's `-->` is closed after the next hand-over, and is not left to reopen when sheaf deletes the thread (red test)
  - Evidence: red then green: test_an_open_comment_on_a_task_line_that_a_later_threads_arrow_closed…
- [x] Class c: two result lines after `_unhidden` closes a left-open comment on the result line become one (test, or the line why not)
  - Evidence: red then green: test_settle_replaces_a_result_whose_open_comment_the_unhiding_closed…
- [x] Class c: a CRLF page keeps one kind of line end for rewritten lines and the result line; `adopt` reports case-duplicate keys under an existing entry (tests)
  - Evidence: CRLF already green (lone-end checks in the CRLF tests); adopt red then green: test_adopt_reports_a_case_duplicate…
- [x] Class b, from 26: a person's plain copy of our pin line, with a sheaf thread in the middle of our own pin line, is recognised as theirs: the next hand-over keeps the copy and replaces our threaded line (red test, the repro above)
  - Evidence: red then green: test_a_persons_plain_copy_of_our_pin_line_is_theirs_when_a_thread_sits_in_the_middle_of_ours
- [x] Class c, from 24: `TheHubsOps` finds sheaf the way the relay does (the interpreter of the configured `sheaf` executable), or says why it skips (test or the line why)
  - Evidence: test_desk_relay.TheHubsOps: sheaf's interpreter from the `sheaf` on PATH (deskcmd.SHEAF), a skip says why; test_a_sheaf_that_is_not_there_says_why_it_skips
- [x] A public `deskfile` function returns an item's own result lines, and `deskscan.over()` uses it instead of the private names `_kinds`, `_logical`, `_own`, `_orders`, `_prev_stands`, `_slot`, `_text` and `_held.record` (existing tidy tests stay green; `grep` shows no private deskfile name left in deskscan.py)
  - Evidence: `deskfile.own_results` and `held_record`; `grep 'deskfile\._' deskscan.py` is empty; tests/test_deskscan.py untouched, 125 OK; test_the_results_of_an_item_come_from_one_public_function…
- [x] Class b, from 31 round 2: a stray `-->` later on the page (`see A --> B`) does not keep a left-open comment hiding its item, and `put` adds no second copy (red test)
  - Evidence: red then green: test_a_stray_arrow_later_on_the_page_does_not_keep_a_left_open_comment_hiding_its_item (`_open_at` counts a stray arrow only before the next item)
- [x] Class b, from 31 round 2: a person's line shaped exactly like a ships line is told from ours, or the known limit is written under "Known limit" with the line why (test or the line why)
  - Evidence: Known limit (below), no code
- [x] Class c, from 31 round 2: a page one write behind with its Recommendation and Handed-over lines removed is still judged behind (red test, or the line why not)
  - Evidence: Known limit (below), no code
- [x] Each fix is red on its review's head, green after, with the commands and results in the report
  - Evidence: each new test was run before its fix (red) and after (green); `python3 -m unittest tests.test_desk.SettleAndPutShapes` 15 OK; boris/32 at the head in the report

## Known limit
- A person's line shaped exactly like a `deskships` line (`    - Outside GitHub: my text` under `What ships:`) is still adopted by `adopt`: the text alone cannot tell it from ours, and `adopt` is a one-time hand command whose result the person can read.
- A page one write behind whose Recommendation and Handed-over lines are gone is not judged behind, and a stale page carrying a press result line is not either (two pin lines show after the next hand-over): the same text is what a person leaves who removed two of our lines and typed a copy of an old pin line, and judging that page behind makes `put` delete the person's text (the A1 hotfix). Nothing is lost either way; the old pin stays as the person's line.
