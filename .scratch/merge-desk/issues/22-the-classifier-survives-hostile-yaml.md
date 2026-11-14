# 22: The classifier survives hostile YAML and odd terminals

**What to fix:** class c left by ticket 21 (Yara), all already in the old `~/.claude/routines/branch_deploys.py`:
1. A billion-laughs YAML alias in `branches:` hangs it via `map(str, patterns)`: cap alias expansion (or the list size) and read the workflow as could-not-parse.
2. About 300 entries of `*-*-*-x`N take 13 s: bound the total work per workflow, not only per pattern.
3. Printing a non-ASCII hint line under an ASCII stdout exits 1 (read as "nothing fires" by a push check): write with errors replaced.
4. (Carried from 18/21) a re-indent that moves a key under another mapping is not caught by the desk's hint comparison; fixing it changes --full output, so it needs deskships to change with it.

**Also from 21 (Yara):** since 21 every pattern with more than 3 quantifiers reads as Unsure (fires), so `v[0-9]+.[0-9]+.[0-9]+-rc[0-9]+` over-asks. A linear-time matcher for GitHub's filter syntax would let those read normally; `a+aa+aa+aa+aa+b` against 320 'a' (pinned in test_branch_deploys.py) must stay fast.

**Blocked by:** 21

**Claimed by:** Carmen 2026-11-14 10:48

**Status:** in-progress

- [x] A billion-laughs alias in branches: answers within 1 s as could-not-parse (test_a_billion_laughs_alias_in_branches_is_a_parse_failure_within_a_second passes; the old script times out on it)
- [x] 300 `*-*-*-x` entries answer within 1 s (test_300_star_patterns_answer_within_a_second passes; NFA matcher, no regex)
- [x] `PYTHONIOENCODING=ascii` with a non-ASCII hint line exits 0 (test_a_hostile_non_ascii_hint_line_under_ascii_stdout_exits_0 passes)
- [x] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo (old vs new, main and dev, default and --full: identical output and exit codes in all 20 runs; tests.test_deskships 42 OK against the new script)
- [ ] Item 4 (re-indent hint comparison) not done: any fix shows the indent on every --full hint line and changes every deskships line; needs Tarek's decision
- [ ] Branch carmen/22 (0744103): Sonnet review GO (carmen-22-sonnet-1.md); waits for one Codex run at 15:00+ before merge
