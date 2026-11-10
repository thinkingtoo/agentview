# 04: the turn text has 103 characters of headroom under its ceiling

**What:** after ticket 02 the injected turn text is 2047 characters (the test's paths), the floor 2000 and the ceiling 2150 (`tests/test_turn_hook.py`, `test_the_instruction_stays_short`). The ceiling is the size the owner approved on 2026-10-22, and the dispatch for 02 forbade moving it, so any growth up to 2150 now passes with no one told. Before 02 the headroom was 38. Decide whether the owner wants the ceiling tightened to the new size.

**Found by:** the Opus bug hunt of PR for ticket 02, 2026-11-11 (class c).

**Blocked by:** None

**Claimed by:** none

**Status:** needs-triage

- [ ] The owner has kept 2150 or set a lower ceiling, and the test says which
