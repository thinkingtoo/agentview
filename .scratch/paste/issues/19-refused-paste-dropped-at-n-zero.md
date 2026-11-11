# 19: A refused Paste said in the ask is dropped when --n is 0

**What to fix:** the turn instruction says "say so in the ask (in the did when --n is above 1)", which leaves --n 0 to the ask. `team-line` keeps the ask only when `n == 1`, so a session that does not count the refused Paste writes the refusal where it is thrown away. Word it "in the did unless --n is 1" (or make team-line keep it).

**Input:** `team-line <sid> --did 'x' --n 0 --ask 'paste create was refused: ...'` — the card shows no refusal.

**Failing lines:** `hooks/turn_line.py:59-60` `Paste is refused (classifier or error), say so in the ask (in the did when --n is above 1)` against `hooks/team-line:28` `ask = args.ask if args.n == 1 else ""`.

**Class:** c. Predates the track.

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** done

**Claimed by:** Samir 2026-11-11

## Evidence

**Samir, 2026-11-11.** Fixed in `team-line`, not in the wording: the same rule is also written in `~/.claude/CLAUDE.md`, and sessions already follow it. With `--n 0` nothing is waiting, so an ask is news, not a question; `team-line` now appends it to the did, which the card shows. `--n 1` and above are unchanged (the ask is kept at 1 and dropped above, as before). The card never shows an ask at 0 anyway (`fleet.py` reads it only when `n == 1`).

Red, `tests.test_stop_hook` on t-compute, before the fix:

```
FAIL: test_an_ask_with_nothing_waiting_is_kept_in_the_did (tests.test_stop_hook.TheWriter...)
AssertionError: 'Mail drafted.' != 'Mail drafted. paste create was refused'
Ran 14 tests in 0.556s
FAILED (failures=1)
```

Green after it, with the tests that read lines and the hook text (`tests.test_stop_hook tests.test_lines tests.test_turn_hook tests.test_announce_sound`):

```
Ran 113 tests in 12.849s
OK (skipped=3)
```
