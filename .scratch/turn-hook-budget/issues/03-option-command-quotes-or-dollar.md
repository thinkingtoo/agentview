# 03: a command offered in an AskUserQuestion option may now go in double quotes

**What:** since ticket 02 the one sentence on where a command goes reads "inside double quotes, or after "$ " at the end of the ask, ..., even when an option of your question offers it". Before, the Paste paragraph said such a command goes "after "$ " in the ask too", so double quotes in mid-ask did not count for that case. `~/.claude/CLAUDE.md` still says "A command he must type goes in the `--ask` line after `$ ` last". The copy button reads quoted text too (README.md, "copy button"), so nothing breaks; the question is only which placement the owner wants, and whether the hook and CLAUDE.md should say the same.

**Found by:** the Opus bug hunt of PR for ticket 02, 2026-11-11 (class c).

**Blocked by:** None

**Claimed by:** none

**Status:** needs-triage

- [ ] The owner has chosen "$ only" or "quotes or $ " for a command offered in an option, and the hook and `~/.claude/CLAUDE.md` say the same
