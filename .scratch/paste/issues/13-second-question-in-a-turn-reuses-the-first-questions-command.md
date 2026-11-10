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

**Claimed by:** Astrid 2026-11-11

**Status:** done

- [x] A test: line with `n` 1 and a command, an AskUserQuestion answered after it in the same turn, a second question open: no guessed command
- [x] The first question of a turn still offers its command (paste/12's tests stay green)

## Answer (Astrid, 2026-11-11)

### The change

The first of the three fixes. Not the hook: its instruction is at its length ceiling, and a PostToolUse hook needs a settings change on every machine.

- **Reader** (`providers/claude.py`, `_absorb`): a `tool_result` for a call named `AskUserQuestion` (not a sidechain's) keeps its record's time as `state["answered"]`, the latest one. `_view` and `session()` hand it over as `answeredAt`, milliseconds since 1970, or None.
- **Contract** (`providers/base.py`): `answeredAt` is an optional field. A provider without it (Codex) keeps paste/12's behaviour.
- **Core** (`fleet.py`): the row carries `answeredAt` (`base.milliseconds`), and `_shown` carries the line's own `at` as `lineAt`. `guessed_commands_of` offers nothing under a question (stuck source `"question"`) when `lineAt <= answeredAt`: that line was written for a question since answered. A line written after the answer is offered again. The `"line"` source (turn over, no dialog) is unchanged; the ticket was about the question.

### Evidence

**Tests**, run on t-compute (laptop load 12 to 14): `test_guessed_commands`: `test_a_second_question_after_the_first_was_answered_offers_nothing` (box 1) and `test_a_line_written_after_the_last_answer_offers_its_command`; `test_needs_you_reader`: `test_the_moment_the_last_question_was_answered_is_handed_over` and `test_an_answer_to_another_tool_is_not_an_answered_question`. Red before the change: the box-1 test failed with `('question', ['bash ~/notes/push-maple.sh']) != ('question', [])` and the reader test with `KeyError: 'answeredAt'`. After: `test_guessed_commands test_needs_you_reader test_needs_you test_concierge_tag test_providers test_columns test_stuck_kinds_reader test_movement_reader test_scan test_fleet test_line_separators`, 520 tests OK, with `fleet.py` and `providers/claude.py` resolved to the t-compute copy. paste/12's question tests are among them and green (box 2).

**The real card.** Two sandbox servers, this branch and a `git archive origin/dev` copy, on free ports, under `env -i` with their own `HOME`, `XDG_STATE_HOME`, `CLAUDE_CONFIG_DIR`, `XDG_RUNTIME_DIR` and tmux socket in `$XDG_RUNTIME_DIR/avA`. Before every request the listener's pid (`ss -ltnp`) was checked for the run's marker and its role in `/proc/<pid>/environ`. One session, Wren: a `sleep` in a pane of the sandbox tmux, a registry record `waiting` / `input needed`, its turn begun by the real `hooks/turn_line.py` and its line written by the real `hooks/team-line` (`--n 1 --ask 'Run the push script, then answer. $ bash ~/maple/push-notes.sh'`).

| Step | dev | fix |
|---|---|---|
| Q1 open, unanswered | COMMAND `bash ~/maple/push-notes.sh` | COMMAND `bash ~/maple/push-notes.sh` |
| Q1 answered, Q2 open in the same turn, no new line | COMMAND `bash ~/maple/push-notes.sh` under Q2 | no COMMAND row |
| A new line for Q2 (`$ bash ~/maple/retitle.sh`) | COMMAND `bash ~/maple/retitle.sh` | COMMAND `bash ~/maple/retitle.sh` |

Headless Chrome screenshots of the three cards (Q1 on the fix server; Q2 on both) show the same as the roster: Wren with NEEDS YOU, "Question", the question with its two options, and the COMMAND row with its copy button only where the table says. Not committed. Real tmux had 9 sessions before and after; both servers and the sandbox tmux were stopped by the pids that carried the marker, and the box was removed.

### Left as it is

- A transcript big enough that the reader starts from its tail can hold an answer whose `AskUserQuestion` call lies before the tail. Its name is then unknown and the answer is not counted: the card offers the command, as before this ticket.
- The clocks: `lineAt` is the hook's `time.time()`, `answeredAt` Claude Code's record timestamp, both from the same machine.

### Reviews

- Code review 1 (Matt Pocock's, run by Astrid): no findings.
- Codex review 1 (Opus fallback, run by Zeynep, Codex out of tokens): no P1 or P2, GO. Its test-only notes are ticket paste/14.
