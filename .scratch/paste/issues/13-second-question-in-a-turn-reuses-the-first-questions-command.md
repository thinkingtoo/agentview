# 13: A second question in the same turn offers the command of the first

**What to build:** a command guessed from a session's line shows beside an open question only when the line was written for that question. A line written before an earlier question of the same turn, one that has since been answered, offers nothing.

**What happens (found in the Opus bug hunt of paste/12, PR #5, 2026-11-11):**
- Since paste/12, `guessed_commands_of` (`fleet.py`) offers the command from the session's own line while an AskUserQuestion is open, on the terms `n` 1 and `m["blocked"]`.
- A line lasts for the whole turn (`lines.fresh`). Answering an AskUserQuestion is a tool result, not a new prompt, so `hooks/turn_line.py` does not begin a new turn.
- The hook's rule asks for a new line only "If the turn ends on an AskUserQuestion" (`hooks/turn_line.py:34`, pinned by `tests/test_turn_hook.py:108`).
- So: a session writes `--n 1 --ask '... $ bash push.sh'`, opens Q1, and the owner answers and runs the script. The session then opens Q2 about something else in the same turn, without writing a new line. Q2's card offers `bash push.sh` with a copy button.
- The concierge brief does this by design: one `ASK` holding several questions is asked one at a time, in the same turn (claude-boss `skills/boss/references/concierge-brief.md`).

**How often:** none of the 53 questions in the transcripts of the six concierges live on 2026-11-11 reused an earlier question's line; each was preceded by a line of its own. The path is real, and nothing in use takes it today.

**Before paste/12:** the same stale line already showed (source `"line"`) once the turn ended with `n` 1 still in it. paste/12 also shows it while Q2 is open, next to an unrelated question.

**Possible fixes (not chosen):**
- The transcript scan (`providers/claude.py`, `scan_session`; it already records answered tool calls in `state["done"]`) keeps the moment the last AskUserQuestion was answered. `guessed_commands_of` then offers nothing under a question when the line's `at` is older than that.
- Or the hook forgets `ask` and `n` when an AskUserQuestion is answered (a PostToolUse hook; it needs a settings change on each machine).
- Or the hook's instruction asks for a line before every AskUserQuestion, not only the last one. The instruction is at its length ceiling (ticket turn-hook-budget 01).

**Blocked by:** None.

**Claimed by:** none

**Status:** needs-triage

- [ ] A test: line with `n` 1 and a command, an AskUserQuestion answered after it in the same turn, a second question open: no guessed command
- [ ] The first question of a turn still offers its command (paste/12's tests stay green)
