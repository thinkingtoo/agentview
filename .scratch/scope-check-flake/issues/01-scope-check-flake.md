# 01: test_scope_check fails one run in four

**What to fix:** `tests/test_scope_check.py`, `Scopes.test_a_process_is_ours_only_if_its_own_environment_says_so` (around line 583) fails intermittently: `sc.carries()` is False right after `Popen(["sleep", ...])`. Measured on clean code: 16 of 60 isolated runs failed on origin/dev e4f8240 (2026-10-19, Hugo), 8 of 30 (Joaquin). Suspected: a fork/exec race, `/proc/<pid>/environ` read before the child has exec'd and carries its environment. Find the cause before changing anything (`mattpocock-skills:diagnosing-bugs`). Fix the test, or `scripts/scope-check` if the race is real there too, without weakening what the check proves.

**Why now:** the overview-build objective needs `python3 -m unittest discover -s tests` to exit 0 on a fresh clone; a test that fails one run in four makes that a coin flip.

**Blocked by:** None

**Claimed by:** Joaquin 2026-10-19 01:45

**Status:** in-progress

- [ ] The cause is named with evidence (what `carries()` read, and when), not guessed
- [ ] 200 isolated runs of the test pass after the fix, and the same loop fails on the old code
- [ ] What scope-check proves is unchanged: each safety line removed in turn still makes a test fail (exit code, not the word "failed")
- [ ] Full unit suite green
