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

**Status:** needs-triage
