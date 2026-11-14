# 21: The classifier never hangs, and never reads a crash as "nothing fires"

**What to fix:** class c left by ticket 18 (Yuki, round 3), in `~/.claude/routines/branch_deploys.py`:
- `+`/`?` are not counted against the pattern blowup cap: `*a+*a+*b` against a 320-character branch hangs. A push check or a desk hand-over then hangs on a hostile workflow.
- A workflow nested about 3000 levels deep raises RecursionError and exits 1, which a push check reads as "nothing fires" (the same failure class 18 fixed for non-UTF-8). Any unexpected exception per workflow must become a `! could not parse` line, exit 0.
- A leading `?` or `+` reads as a literal instead of Unsure.
- (From 18's fourth bullet, decided not to change there) a re-indent that moves a key under another mapping is not caught by the desk's hint comparison.

**Blocked by:** 18

**Claimed by:** Yara 2026-11-14 03:09

**Status:** done

- [x] `*a+*a+*b` against a 320-character branch answers within 1 s (test with a timeout) — test_plus_and_question_mark_count_against_the_blowup_cap, red on the old script, passes; `+`/`?`/`*` all count toward the cap (> 3 = Unsure); ~/.claude main 12b5c0e
- [x] A 3000-deep workflow gives a could-not-parse line and exit 0 (test) — test_a_workflow_nested_3000_deep_..., any Exception per workflow is caught; also checked block-style nesting in review
- [x] A leading `?`/`+` pattern reads as Unsure (test) — test_a_leading_plus_or_question_mark_reads_as_unsure...
- [x] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo — old vs new script, default and --full, output + exit code, 6 branch names each (main dev master feature/x release/1.2 v1.10.1): no diff; tests.test_deskships 42 OK against my copy

Not done here (ticket 22 per Tarek): billion-laughs aliases, many-pattern slowness, non-ASCII print under ASCII stdout, the re-indent hint comparison, and 4+-quantifier version patterns reading as Unsure (over-asks, safe direction). Reviews: yara-21-opus-1-2.md, yara-21-sonnet-2.md in agentview-wt. Codex run on merged main still owed at 15:00.
