# 26: A person's exact copy of AgentView's line is not taken for ours

**What to fix:** class b left by ticket 19 (Codex on ae1df80, /home/tiroir/Projects/agentview-wt/nuno-19-codex-4.md, finding 4). Ownership is matched by line text, first occurrence: when the person pastes a byte-identical copy of AgentView's current line (a pin, a recommendation) above the recorded one, `_kinds()` takes the copy for ours and the real line for theirs. A later hand-over replaces the person's copy and keeps the stale line, and `parse()` can then read the stale pin. The record stores no positions, so the fix needs a record format change: store each owned line's ordinal among identical lines in the block (or its index), and match by that.

**Same class (Sonnet review nuno-19-sonnet-5.md, b1):** a person line with the same text as a recorded line (an identical `Recommendation:` line, say) is taken for ours, first match wins; ticket 19's `desk adopt` avoids it on the live desk only because that page holds no person-written line.

**Blocked by:** 19

**Claimed by:** Hakim 2026-11-14 15:51

**Status:** done

- [x] A person's byte-identical copy of the pin line above ours: the next hand-over replaces ours and keeps theirs (test): tests/test_desk.py CopyOfOurLine.test_a_copy_of_the_pin_line_above_the_recommendation_is_kept_and_ours_is_replaced, red on 51dbef6's deskfile.py, green at 0e20d0d
- [x] parse().pinned reads the recorded occurrence, not the first (test): CopyOfOurLine.test_the_pin_is_read_from_the_recorded_place_not_the_first_line_of_that_text (through `_kinds`, which `parse` reads the pin by: two identical lines give the same commit, so a parse-level test cannot tell them apart)
- [x] A record written before this change is still read (no item loses its pin on upgrade) (test): CopyOfOurLine.test_a_record_written_before_ordinals_is_still_read_and_is_rewritten_with_them; and on the live desk copy taken before the restart (record with no `at`), the new code read #293 = 11ff860 and install:sheafmd = 8bcd20b

**Done 2026-11-14 (Hakim):** merged into dev as 0e20d0d (code, fast-forward from 51dbef6), restarted 16:02, MainPID 240292, 8765 answers 200, claude count 45 before and after, cgroup held the server only, no `pressing` without a result. Sonnet round 1 GO (/home/tiroir/Projects/agentview-wt/hakim-26-sonnet-1.md). History check clean. Touched test files green: test_desk 114, test_deskinstall 48, test_desk_relay 59, test_deskring 12, test_deskrotate 17, test_deskwatch 83, test_deskscan 118, test_deskships 42. `hooks/desk status` identical around the restart except install:sheafmd, which the scan re-handed at 16:02 at the newer main of sheaf (027198f, pinned there, written in the new format with `at`); #293 still waiting, pinned 11ff860.

**Limit (Tarek accepted, 2026-11-14):** a copy next to ours that the record's order cannot place (nothing between that gives it away) cannot be told from ours by its text; the recorded ordinal decides. The line is the same text, so the pin it gives is the same commit. Codex owed on the merged head at 20:00+.
