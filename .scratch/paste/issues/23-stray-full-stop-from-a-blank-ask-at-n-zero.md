# 23: A blank or space-ended ask at --n 0 leaves a stray full stop in the did

**What to fix:** with `--n 0`, `team-line` tests the ask's last character before any whitespace is normalised, so a blank ask still joins the did and a space-ended one gets a full stop after the space. Normalise the ask first (`a = " ".join(args.ask.split())`) and use it only when it is not empty.

**Input:**
- `team-line <sid> --did 'Mail drafted.' --n 0 --ask '   '` writes the did `'. Mail drafted.'`
- `--ask 'refused '` writes `'refused . Mail drafted.'`
- `--ask 'é…'` writes `'é…. x'` (the ellipsis is not in the stop set)

No crash, exit 0.

**Failing lines:** `hooks/team-line:34-36` at 7dc96ed:

```python
    if args.n == 0 and args.ask:
        stop = "" if args.ask[-1] in ".!?:;" else "."
        did = f"{args.ask}{stop} {did}" if did else args.ask
```

**Class:** c. Introduced by paste/19 (PR 29).

**Found in:** PR 29 hunt (Samir, Opus), 2026-11-11, reproduced against a scratch `XDG_STATE_HOME`.

**Blocked by:** None.

**Status:** done
