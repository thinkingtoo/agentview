# 22: The classifier survives hostile YAML and odd terminals

**What to fix:** class c left by ticket 21 (Yara), all already in the old `~/.claude/routines/branch_deploys.py`:
1. A billion-laughs YAML alias in `branches:` hangs it via `map(str, patterns)`: cap alias expansion (or the list size) and read the workflow as could-not-parse.
2. About 300 entries of `*-*-*-x`N take 13 s: bound the total work per workflow, not only per pattern.
3. Printing a non-ASCII hint line under an ASCII stdout exits 1 (read as "nothing fires" by a push check): write with errors replaced.
4. (Carried from 18/21) a re-indent that moves a key under another mapping is not caught by the desk's hint comparison; fixing it changes --full output, so it needs deskships to change with it.

**Also from 21 (Yara):** since 21 every pattern with more than 3 quantifiers reads as Unsure (fires), so `v[0-9]+.[0-9]+.[0-9]+-rc[0-9]+` over-asks. A linear-time matcher for GitHub's filter syntax would let those read normally; `a+aa+aa+aa+aa+b` against 320 'a' (pinned in test_branch_deploys.py) must stay fast.

**Blocked by:** 21

**Claimed by:** Carmen 2026-11-14 10:48

**Status:** done

- [x] A billion-laughs alias in branches: answers within 1 s as could-not-parse (test_a_billion_laughs_alias_in_branches_is_a_parse_failure_within_a_second passes; the old script times out on it)
- [x] 300 `*-*-*-x` entries answer within 1 s (test_300_star_patterns_answer_within_a_second passes; NFA matcher, no regex)
- [x] `PYTHONIOENCODING=ascii` with a non-ASCII hint line exits 0 (test_a_hostile_non_ascii_hint_line_under_ascii_stdout_exits_0 passes)
- [x] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo (old vs new, main and dev, default and --full: identical output and exit codes in all 20 runs; tests.test_deskships 42 OK against the new script)
- [x] Item 4 (re-indent hint comparison): not done here on purpose, any fix shows the indent on every --full hint line and changes every deskships line; carried to ticket 25 (its first paragraph), which digests the structure instead
- [x] Merged: carmen/22 fast-forwarded into ~/.claude main at b087c9e (nothing deploys there: `branch_deploys.py ~/.claude main` exit 1; no CI runs on it, check-runs total_count 0); reviews sonnet-1 GO, sonnet-5 NO-GO (class a, fixed), sonnet-6 GO with class c only (carmen-22-sonnet-6.md). Codex on the merged head is owed at 20:00 or later (Tarek runs it); not a box here

## Rounds 4 to 6 (Nour, then Bram, 2026-11-14), branch carmen/22 to b087c9e
- Round 4 (609cc2f). Round-3 bombs closed: `merged_pairs` keeps an in-progress set; a merge value (or merge-sequence item) that is a mapping still being defined raises TooMuch. Red-first tests: `m: &a {<<: [*a x2000], k0..k9998: 0}` and `m: &a {k0..k9998, c0..c1999: {<<: *a}}` each answer `! could not parse: TooMuch`, exit 0.
- Round 4 backstop: `main()` arms `signal.setitimer(ITIMER_REAL, limit)` before any parsing. On expiry the file in hand and every file after it print `! could not parse: the time limit (N s) ran out`, exit 0 (fires). PyYAML 6.0.3 `_Loader` subclasses the pure-Python `SafeLoader`, so SIGALRM is delivered between bytecodes. Limit 10 s = about 100x the slowest of 20 real runs (0.101 s, monorepo dev).
- Round 5 (118f186, fixes sonnet-4): the alarm stays armed over all of main, printing and `deploy_hints` included; `read_workflow` reads only a regular file (S_ISREG after following symlinks, checked again on the open fd, O_NONBLOCK) whose realpath is inside the checkout, at most 1 000 000 bytes. Cap = 100x the largest real workflow: sheaf ci.yml 9 478 bytes; monorepo tiroir-central-deploy.yml 6 398; thinkingtoo project-sync.yml 3 554 (rounded up to 1 000 000; agentview and ~/.claude have none larger). `deploy_hints` catches Exception. BRANCH_DEPLOYS_TIME_LIMIT: finite float, default otherwise.
- Round 5 red first (6 of 7 failed on the old script): test_a_symlink_to_dev_zero_is_could_not_parse, test_a_fifo_is_could_not_parse_and_does_not_block, test_a_symlink_to_a_file_outside_the_checkout_is_could_not_parse, test_a_200_MB_file_is_could_not_parse, test_a_bad_time_limit_value_falls_back_to_the_default, test_a_zero_time_limit_does_not_disarm_the_alarm; test_a_symlink_inside_the_checkout_is_still_read passes before and after. Each gives the line, exit 0, under 2 s.
- Round 6 (b087c9e, fixes sonnet-5 finding 1 and 2): after TimeUp the hit lookup is a set (test_100000_files_after_the_time_limit_finish_in_seconds, red by timeout before; 1.3 s for 100 000 and 3.7 s for 300 000 files in the review); the limit has a floor of 0.1 s, below it the default. The five timing tests that flaked under laptop load now bound at 5 s (the bombs ran 12 s and more).
- Evidence at b087c9e: routines/tests/test_branch_deploys.py 55 passed (two runs); tests.test_deskships 42 OK with deskships.CLASSIFIER pointed at the branch script; old (origin/main before the merge) vs new output + exit code identical in 20 of 20 runs (5 repos x main/dev x default/--full); the sonnet-5 reviewer's 536 runs also 0 differences.
- Left as class c, in ticket 25: a TimeUp between `out.append` and `shown += 1` could print one name twice (two bytecodes); a closed stdout pipe gives a BrokenPipeError traceback, exit 1; a file where every line says "deploy" prints every line; a file name with a newline can add fake output lines; a stdout write failure exits 120 as the old script does.
