# 10: A denied Paste is said out loud, and a command Thierry types reaches the ask line

**What to build:** causes A and B of `/home/tiroir/Projects/agentview-wt/reviews/paste-not-seen-diagnosis.md`. On 2026-10-22 18:42 Casper's `hooks/paste create` for a command was refused by the auto-mode classifier ([Auto-Mode Bypass]); Casper fell back to an AskUserQuestion and never said the Paste was refused, so Thierry looked for a Paste that did not exist. And the rule names no home for a command Thierry must type that sits only inside an AskUserQuestion option (2 sessions today). Thierry approved (2026-10-22 18:5x) changing both `hooks/turn_line.py` (`ASK`) and the "Clipboard (Leave a Paste)" section of `~/.claude/CLAUDE.md`.

The rule, in the reminder and in CLAUDE.md, in a sentence or two each:
1. When `paste create` is refused, the session says so in its `--ask` line and puts the text itself in its AskUserQuestion or reply; never silent.
2. A command Thierry must type goes in the `--ask` line (after `$ `), also when it is offered in an AskUserQuestion option. The copied command stays without `!` (Thierry adds it; memory `copy-button-never-adds-bang`).

**Blocked by:** None (can start immediately).

**Claimed by:** Lennart 2026-10-22 18:55

**Status:** in-progress

- [ ] `turn_line.py` reminder text says both points; a test pins the wording (fails before the change)
- [ ] `~/.claude/CLAUDE.md` "Clipboard (Leave a Paste)" carries both points, surgical diff only in that section, committed and pushed in `~/.claude` by path
- [ ] Review GO (mattpocock-skills:code-review, then `/codex-review` through the runner, Opus fallback at once), test files touched run locally; the reminder seen live in a fresh session's hook output
