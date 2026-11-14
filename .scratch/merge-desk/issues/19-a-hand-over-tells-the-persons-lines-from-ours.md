# 19: A hand-over tells the person's lines from AgentView's

**What to fix:** ticket 16's `deskfile.carry` replaces AgentView's own lines by shape, so three cases still lose or move the person's text (Alonso, 16's limits, class c): a person's own 4-space note directly under `What ships:` reads as a ships bullet and is replaced; a person line that exactly matches one of AgentView's line shapes is replaced; a thread whose line is gone moves to the end of the item and its quote anchor may no longer match. Mark AgentView's lines unambiguously (or keep a record of what AgentView wrote last) so nothing the person wrote is ever taken for ours.

**Waiting (Tarek, 2026-11-14):** fixes on branch nuno/19 head ae1df80 (round-3 findings 1-2); owes one Codex run at 15:00+ on that head (nuno-19-codex-4.md), then boxes + merge. Handoff: handoff-Maja-2026-11-14.md.

**Blocked by:** 16

**Claimed by:** Maja 2026-11-14 02:59

**Status:** done

- [x] A person's 4-space note under What ships survives a re-hand-over (test): tests/test_desk.py OwnRecord.test_a_note_of_the_persons_under_what_ships_survives_a_new_hand_over, passed (108 passed in test_desk.py at 5059517); also test_adopt_does_not_take_an_indented_person_line_outside_the_ships_list
- [x] A person line shaped like "  - Recommendation: ..." survives (test): OwnRecord.test_a_person_line_shaped_like_a_recommendation_survives and test_person_lines_shaped_like_the_pinned_line_the_handed_over_line_and_a_result_survive, passed; red on the ae1df80 code for the no-record cases (5 of 5 new tests failed there)
- [x] A thread whose line is replaced keeps an anchor sheaf still finds (test against sheaf's anchor rule): RehandOver.test_a_thread_on_a_line_the_new_block_no_longer_has_stays_on_the_item and test_a_thread_moved_to_the_end_is_still_there_after_a_second_hand_over, passed

**Done 2026-11-14 (Runa):** merged into dev as 5059517 (code), restarted 15:49, MainPID 3871838, 8765 answers 200, claude count 45 before and after. Reviews: Sonnet rounds 5-8 in /home/tiroir/Projects/agentview-wt/nuno-19-sonnet-{5,6,7,8}.md, round 8 GO. Codex owed at 20:00+ on the merged head (nuno-19-codex-5.md). Follow-ups: tickets 26, 27. `desk adopt` ran once on the live desk: adopted 5 items, skipped none, page byte-identical, `hooks/desk status` identical around it, #293 reads 11ff860 from the record, install:sheafmd 8bcd20b. Note: the scan re-handed install:sheafmd at restart, before adopt ran, so its block holds the 15:43 lines (the person's, by the rule) above the recorded 15:49 lines: harmless, the pin comes from the recorded line.
