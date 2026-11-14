# 33: `tidy` trusts only our own result lines (deskscan.py, class a)

**What to build:** `over()` in `deskscan.py` judges an item's story over from `results(it.block)`, every result-shaped line in the block, without asking the ownership record. Found by Codex on ticket 19, head 5059517, review file /home/tiroir/Projects/agentview-wt/nuno-19-codex-6.md (Codex cited `deskscan.py:449`; the logic is `over()`, lines 431-445, `said = results(it.block)` at 439 and the `any(l.startswith(("  - Merged", ...)) for l in said)` test at 441).

Failing scenario: an item has an old `merged` event in the history log (a day or more ago). The person writes their own line `  - Merged at 12:00` in the item. AgentView's real result line was removed or changed. `over()` takes the person's line for ours, so `tidy()` judges the story complete and deletes the whole item, with the person's notes in it. The same shape holds for the `Installed` and `Already installed` lines of the `installed` branch (443-445) and for `NOT_WELL`.

`over()` reads the record of the item (`deskfile` `_own`) and counts a result-shaped line only when the record says the line is ours. An item with no record is never tidied by its result lines.

**Blocked by:** none

Note: deskscan.py only; may run beside the other open tickets. If it needs a `deskfile` function from ticket 31, take it as it is on dev.

**Claimed by:** Gaspar 2026-11-14 20:11

**Status:** done

## Acceptance criteria
- [x] A person's `  - Merged at 12:00` line, with an old `merged` event and no result line of ours in the record, does not make `over()` true, and `tidy()` keeps the item and its notes (red test) — test_a_merged_line_the_person_typed_does_not_make_the_story_over (+ ..._wrote_over_ours...): red on 1384906, green on e510918
- [x] The same for the `installed` branch: a person's `  - Installed` line does not make the story over (red test) — test_an_installed_line_the_person_typed... and ..._added_by_the_person_to_an_item_we_never_settled...: red on 1384906, green
- [x] An item whose result line is ours (the record says so), a day after the event, is still tidied (existing tests stay green) — the 116 existing tests of tests/test_deskscan.py stay green (merged item older than a day leaves; install item at its pin leaves)
- [x] An item with no ownership record is not tidied on the strength of its result lines (red test) — test_an_item_with_no_record_is_not_tidied_on_the_strength_of_its_result_lines: red on 1384906, green
- [x] `tidy()` still judges again under the desk lock on the text the drop is made on (existing test stays green) — existing tidy tests green; change() still calls over() on the text under the lock
- [x] Red on 5059517, green after, with the commands and results in the report — on dev 1384906 (5059517's deskscan is what dev holds): `python3 -I tests/test_deskscan.py` = 6 FAILED of 124 with deskscan.py from 1384906; on e510918 = 125 tests OK
