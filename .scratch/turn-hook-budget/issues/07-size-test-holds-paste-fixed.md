# 07: The checkout-path size test holds PASTE fixed

**What to fix:** `test_the_size_does_not_depend_on_where_the_checkout_lives` patches `WRITER` only. The checkout path also enters through `PASTE`, twice, so the instruction grows by three times the hooks directory's length and the test cannot see it. Patch both (or measure through `_commands_in`), and state the real dependency.

**Failing lines:** `tests/test_turn_hook.py:126-133`:

```python
        for where in ("/a/hooks/team-line", "/home/alice/Projects/agentview-wt-06/hooks/team-line"):
            with mock.patch.object(turn_line, "WRITER", Path(where)):
```

**Input:** a worktree at `/home/tiroir/Projects/agentview-wt/Kwame/hooks` gives 2077 with a UUID (the live path gives 2050); a hooks directory about 34 characters longer than the test's `/home/alice/Projects/agentview/hooks` is over 2150 and no test fails.

**Class:** c. Unchanged in the range.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Claimed by:** Anton 2026-11-11

**Status:** done

- [x] The test moves both commands through `_commands_in` and states the real dependency: three times the hooks directory
  Evidence, red (t-compute, test through `_commands_in`, still subtracting the path once): `tests.test_turn_hook` `FAIL: test_the_size_grows_with_the_hooks_directory_and_nothing_else_of_the_checkout`, `AssertionError: 2 != 1`.
  Evidence, green (t-compute, subtracting `3 * len(hooks)`): `tests.test_turn_hook tests.test_guessed_commands tests.test_needs_you_reader tests.test_movement_reader tests.test_movement_provider` "Ran 297 tests in 22.409s" / "OK". The test was renamed from `test_the_size_does_not_depend_on_where_the_checkout_lives`, and its comment gives the rule: a hooks directory k characters longer than the ceiling tests' 36 adds 3k. `hooks/turn_line.py` is unchanged.

