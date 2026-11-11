# 19: A refused Paste said in the ask is dropped when --n is 0

**What to fix:** the turn instruction says "say so in the ask (in the did when --n is above 1)", which leaves --n 0 to the ask. `team-line` keeps the ask only when `n == 1`, so a session that does not count the refused Paste writes the refusal where it is thrown away. Word it "in the did unless --n is 1" (or make team-line keep it).

**Input:** `team-line <sid> --did 'x' --n 0 --ask 'paste create was refused: ...'` — the card shows no refusal.

**Failing lines:** `hooks/turn_line.py:59-60` `Paste is refused (classifier or error), say so in the ask (in the did when --n is above 1)` against `hooks/team-line:28` `ask = args.ask if args.n == 1 else ""`.

**Class:** c. Predates the track.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
