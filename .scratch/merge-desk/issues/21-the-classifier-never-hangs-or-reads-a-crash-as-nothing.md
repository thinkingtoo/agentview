# 21: The classifier never hangs, and never reads a crash as "nothing fires"

**What to fix:** class c left by ticket 18 (Yuki, round 3), in `~/.claude/routines/branch_deploys.py`:
- `+`/`?` are not counted against the pattern blowup cap: `*a+*a+*b` against a 320-character branch hangs. A push check or a desk hand-over then hangs on a hostile workflow.
- A workflow nested about 3000 levels deep raises RecursionError and exits 1, which a push check reads as "nothing fires" (the same failure class 18 fixed for non-UTF-8). Any unexpected exception per workflow must become a `! could not parse` line, exit 0.
- A leading `?` or `+` reads as a literal instead of Unsure.
- (From 18's fourth bullet, decided not to change there) a re-indent that moves a key under another mapping is not caught by the desk's hint comparison.

**Blocked by:** 18

**Claimed by:** Yara 2026-11-14 03:09

**Status:** in-progress

- [ ] `*a+*a+*b` against a 320-character branch answers within 1 s (test with a timeout)
- [ ] A 3000-deep workflow gives a could-not-parse line and exit 0 (test)
- [ ] A leading `?`/`+` pattern reads as Unsure (test)
- [ ] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo
