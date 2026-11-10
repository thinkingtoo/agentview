# 14: Pin the answered-question reader with the tests the bug hunt of paste/13 named

**What to build:** reader tests for `state["answered"]` (`providers/claude.py` `_absorb`, ticket paste/13) on the paths the first tests leave open. Production code does not change.

**Found in:** Codex review 1 of PR #11 (Opus fallback, run by Zeynep, 2026-11-11). It found no defect. These are test gaps only.

**Blocked by:** None.

**Status:** needs-triage

- [ ] `test_an_answer_to_another_tool_is_not_an_answered_question` asserts the key is there (`assertIn`) and is None. Today `.get()` would also pass if the key were dropped.
- [ ] A split read: the `AskUserQuestion` tool_use is absorbed on one scan, and its tool_result is appended and absorbed on a later one. `answeredAt` is set.
- [ ] A sidechain tool_result for an `AskUserQuestion` leaves `answeredAt` None.
- [ ] An older answer read after a newer one does not lower `answeredAt`.
- [ ] `guessed_commands_of` at `lineAt == answeredAt` offers nothing (the `<=` edge).
