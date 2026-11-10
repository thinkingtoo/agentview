# 14: Pin the answered-question reader with the tests the bug hunt of paste/13 named

**What to build:** reader tests for `state["answered"]` (`providers/claude.py` `_absorb`, ticket paste/13) on the paths the first tests leave open. Production code does not change.

**Found in:** Codex review 1 of PR #11 (Opus fallback, run by Zeynep, 2026-11-11). It found no defect. These are test gaps only.

**Blocked by:** None.

**Claimed by:** Pablo 2026-11-11

**Status:** done

- [x] `test_an_answer_to_another_tool_is_not_an_answered_question` asserts the key is there (`assertIn`) and is None. Today `.get()` would also pass if the key were dropped.
- [x] A split read: the `AskUserQuestion` tool_use is absorbed on one scan, and its tool_result is appended and absorbed on a later one. `answeredAt` is set.
- [x] A sidechain tool_result for an `AskUserQuestion` leaves `answeredAt` None.
- [x] An older answer read after a newer one does not lower `answeredAt`.
- [x] `guessed_commands_of` at `lineAt == answeredAt` offers nothing (the `<=` edge).

## Comments

**Pablo, 2026-11-11.** Tests only; production code unchanged. Run on t-compute at `52f4356`, and again at `f07790b` after the review changes with the same results, clone under `/home/tcompute/tmp/`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<clone>/tests`, `fleet`, `providers.claude` and `test_movement_provider` all imported from the clone: `python3 -m unittest tests.test_needs_you_reader tests.test_guessed_commands` "Ran 180 tests", "OK". Clone removed.

Each new test against a one-line mutation of the code it pins, `__pycache__` cleared after mutating and after restoring; every test passes again once restored:

| Box | Test | Mutation | Mutated |
|---|---|---|---|
| 1 | `test_an_answer_to_another_tool_is_not_an_answered_question` | `providers/claude.py`: drop `"answeredAt": summary["answeredAt"],` from the row | FAILED (failures=1) |
| 2 | `test_an_answer_read_after_its_question_is_still_an_answered_question` | `providers/claude.py`: `list(state["uses"])[:-MAX_USES]` → `list(state["uses"])` (every call forgotten after a read) | FAILED (errors=1): `answeredAt` None |
| 3 | `test_a_subagent_answering_its_own_question_is_not_an_answered_question` | `providers/claude.py`: drop `and not rec.get("isSidechain")` from the answer check | FAILED (failures=1) |
| 4 | `test_an_older_answer_read_after_a_newer_one_does_not_move_the_moment_back` | `providers/claude.py`: `max(state["answered"] or 0, answered)` → `answered` | FAILED (failures=1) |
| 5 | `test_a_line_written_the_moment_the_last_answer_came_offers_nothing` (in `tests/test_guessed_commands.py`) | `fleet.py`: `(m["lineAt"] or 0) <= m["answeredAt"]` → `<` | FAILED (failures=1) |
| 4 | same test, after the bug hunt (c1): it also asserts the older answer's call is still known | `providers/claude.py`: `list(state["uses"])[:-MAX_USES]` → `list(state["uses"])` | FAILED (failures=1); passed before f07790b |

Reviews: Matt code-review (Standards 0 hard, 2 of 4 judgement calls fixed; Spec 0) and Codex review 1 (run by Pablo, Opus): no class a or b; c1 fixed in f07790b. Files in `/home/tiroir/Projects/agentview-wt/Pablo-reviews/`.
