# 22: The cold-start tail can cut a question's tool_use from its answer

**What to fix (or pin as accepted):** on first sight of a transcript over `COLD_BYTES` (2 MB), e.g. after an agentview restart, only the tail is absorbed. If Q1's AskUserQuestion `tool_use` lies before the cut and its `tool_result` after, `state["uses"]` has no Q1, the answer is not counted, `answeredAt` stays None, and Q2's card offers Q1's command (paste/13 undone for that session).

**Input:** a transcript over 2 MB whose cut point falls between Q1's `tool_use` and `tool_result` records, read cold. The two are written next to each other, so this is rare.

**Failing lines:** `providers/base.py:313-316`:

```python
        if state["offset"] == 0 and stat.st_size > COLD_BYTES:
            # First sight of a large file. Every value is a *latest* one, so
            # the tail answers them; what it cannot, `cold` reads once.
            text, offset = read_from(path, stat.st_size - COLD_BYTES)
```

**Class:** c (traced; no test covers it).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Anton 2026-11-11

**Status:** done

- [x] An answer whose question lies before the cold-start cut still sets `answeredAt`
  Fix: `providers/claude.py` `_absorb()`. When the call a tool result answers is unknown, the record itself is checked (`_answers`). Claude Code writes `toolUseResult` with `questions` and `answers` beside an AskUserQuestion's result; this was checked on real transcripts on 2026-11-11. A Bash result (`stdout`/`stderr`) does not count.
  Evidence, red (t-compute, before the fix): `tests.test_needs_you_reader` `FAIL: test_an_answer_whose_question_lies_before_a_cold_start_is_still_an_answered_question`, `AssertionError: unexpectedly None` (and the test asserts that `toolu_1` is absent from `uses`, so the cut did fall between the two records).
  Evidence, green (t-compute, after): the 297-test run above "OK", plus the 12 other test modules that import `providers.claude` (`test_boss_marker` ... `test_stuck_kinds_reader`), "Ran 341 tests in 19.244s" / "OK". `test_another_tools_result_past_a_cold_start_is_not_an_answered_question` covers the negative case.

