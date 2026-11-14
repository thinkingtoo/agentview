# 18: The classifier reads every workflow the way GitHub would

**What to fix:** follow-ups from ticket 14 (Samir), all in `~/.claude/routines/branch_deploys.py` (the ~/.claude repo; every session's push check runs it, so default output and exit codes change only where they were wrong):
- A non-UTF-8 workflow crashes it with exit 1, which a push check reads as "nothing fires". Read with errors replaced and say the file could not be decoded.
- `matches()` uses fnmatch, but GitHub's branch filters read `+` as one-or-more (`release-[0-9]+`), so such a deploy reads as not firing. Follow GitHub's filter pattern syntax.
- YAML scalars in branch lists (`[1.10]`, `[yes]`) are compared via `str()` after YAML has turned them into a float/bool: read them as the strings GitHub sees.
- The desk strips spaces and tabs from hint text, so a re-indented hint line compares equal (class c; decide whether indentation matters for a run line).

**Blocked by:** 14

**Claimed by:** Yuki 2026-11-14 02:43

**Status:** in-progress

- [ ] A non-UTF-8 workflow gives a parse-failure line, not exit 1 (test)
- [ ] `branches: [release-[0-9]+]` matches `release-12` as GitHub does (test)
- [ ] `branches: [1.10]` and `[yes]` match the branches named `1.10` and `yes` (test)
- [ ] Default output stays byte-identical on the monorepo, agentview, sheaf and ~/.claude
