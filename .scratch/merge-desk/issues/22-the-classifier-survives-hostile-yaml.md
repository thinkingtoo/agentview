# 22: The classifier survives hostile YAML and odd terminals

**What to fix:** class c left by ticket 21 (Yara), all already in the old `~/.claude/routines/branch_deploys.py`:
1. A billion-laughs YAML alias in `branches:` hangs it via `map(str, patterns)`: cap alias expansion (or the list size) and read the workflow as could-not-parse.
2. About 300 entries of `*-*-*-x`N take 13 s: bound the total work per workflow, not only per pattern.
3. Printing a non-ASCII hint line under an ASCII stdout exits 1 (read as "nothing fires" by a push check): write with errors replaced.
4. (Carried from 18/21) a re-indent that moves a key under another mapping is not caught by the desk's hint comparison; fixing it changes --full output, so it needs deskships to change with it.

**Blocked by:** 21

**Status:** ready-for-agent

- [ ] A billion-laughs alias in branches: answers within 1 s as could-not-parse (test with a timeout)
- [ ] 300 `*-*-*-x` entries answer within 1 s (test)
- [ ] `PYTHONIOENCODING=ascii` with a non-ASCII hint line exits 0 (test)
- [ ] Default output stays byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo
