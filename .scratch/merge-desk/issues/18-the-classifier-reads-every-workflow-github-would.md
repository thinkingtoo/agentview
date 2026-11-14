# 18: The classifier reads every workflow the way GitHub would

**What to fix:** follow-ups from ticket 14 (Samir), all in `~/.claude/routines/branch_deploys.py` (the ~/.claude repo; every session's push check runs it, so default output and exit codes change only where they were wrong):
- A non-UTF-8 workflow crashes it with exit 1, which a push check reads as "nothing fires". Read with errors replaced and say the file could not be decoded.
- `matches()` uses fnmatch, but GitHub's branch filters read `+` as one-or-more (`release-[0-9]+`), so such a deploy reads as not firing. Follow GitHub's filter pattern syntax.
- YAML scalars in branch lists (`[1.10]`, `[yes]`) are compared via `str()` after YAML has turned them into a float/bool: read them as the strings GitHub sees.
- The desk strips spaces and tabs from hint text, so a re-indented hint line compares equal (class c; decide whether indentation matters for a run line).

**Blocked by:** 14

**Claimed by:** Yuki 2026-11-14 02:43

**Status:** done

- [x] A non-UTF-8 workflow gives a parse-failure line, not exit 1 (test)
- [x] `branches: [release-[0-9]+]` matches `release-12` as GitHub does (test)
- [x] `branches: [1.10]` and `[yes]` match the branches named `1.10` and `yes` (test)
- [x] Default output stays byte-identical on the monorepo, agentview, sheaf and ~/.claude

## Done (Yuki, 2026-11-14)
Merged to ~/.claude main as d35668b (ff of yuki/18), pushed. Tests: routines/tests/test_branch_deploys.py, 26 passed; tests.test_deskships 42 OK against this version (run from agentview-wt/yuki-18-av with HOME pointing at a .claude symlinking it).
- Default and --full output and exit codes byte-identical to the old script on monorepo, agentview, sheaf, ~/.claude, thinkingtoo, for main and dev.
- Fourth bullet (re-indented hint line): decided no change. --full keeps the line number and the text without indentation; keeping indentation would change the line format the desk compares. A re-indent that moves a key under another mapping is not caught; ticket it if wanted.
- Extra, from review: merge keys (`<<: *a`) still merge; exclusions (`!pat`, branches-ignore) read `*` strictly; patterns it will not guess at (second quantifier, class outside alphanumeric ranges, more than 3 stars) read as firing.
- Reviews (Codex out of tokens, Opus): /home/tiroir/Projects/agentview-wt/ holds only the Codex stub yuki-18-codex-1.md; three Opus rounds were run as subagents (NO-GO, NO-GO, GO), findings fixed in between.
- Left open (class c, from round 3): `+`/`?` not counted against the blowup cap (`*a+*a+*b` on a 320-char branch hangs); RecursionError on a 3000-deep YAML exits 1; a leading `?`/`+` reads literal, not Unsure.
