# 24: A negative --n still drops the ask

**What to fix:** `team-line` keeps the ask in the did only when `n == 0`, while the count is clamped to 0 later. A negative `--n` therefore loses the ask exactly as paste/19 did for 0. Test `args.n <= 0`.

**Input:** `team-line <sid> --did 'x' --n -1 --ask 'refused'` writes `'x' n=0`: the refusal is gone. No session should pass a negative count, so this is the paste/19 loss for an input that should not occur.

**Failing lines:** `hooks/team-line:29` and `:34` at 7dc96ed:

```python
    ask = args.ask if args.n == 1 else ""
    ...
    if args.n == 0 and args.ask:
```

against the clamp in `lines.py:278` `def _count(value):`, which writes n=0.

**Class:** c. Introduced by paste/19 (PR 29).

**Found in:** PR 29 hunt (Samir, Opus), 2026-11-11, reproduced against a scratch `XDG_STATE_HOME`.

**Blocked by:** None.

**Status:** needs-triage
