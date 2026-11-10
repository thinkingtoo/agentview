# 12: A command in the ask line has no copy button while the session's question is open

**What to build:** while a session's AskUserQuestion is open and its `n` is 1, the card also offers the command guessed from the session's ask line, in the existing guessed box with its copy button. Today it offers none.

**What happened (2026-11-05, about 18:15 CET):** a boss session needed the owner to run a command. As the rule says (CLAUDE.md, "Clipboard (Leave a Paste)"; ticket paste/10), it ran `team-line --n 1 --ask 'Type this here: $ bash ~/.claude/pm/scrub3/push.sh'` and then opened its AskUserQuestion. The owner ran the command by hand and said: "I ran it, but you didn't put the cmd in agentview."

**Cause (checked 2026-11-05):**
- `ask_commands.guess("Type this here: $ bash ~/.claude/pm/scrub3/push.sh")` returns `['bash ~/.claude/pm/scrub3/push.sh']`, so extraction is not at fault.
- `guessed_commands_of` (`fleet.py:1236`) returns `[]` unless `stuck["source"] == "line"`. An open AskUserQuestion gives source `"question"`. Called with `m = {"n": 1, "ask": <that text>}`: `source "line"` returns the command, `source "question"` returns `[]`.
- The docstring does this on purpose ("an open dialog is shown over it"). The rule in CLAUDE.md and paste/10 assume the opposite: sessions run `team-line` right before the question, and the command goes in the ask "also when an AskUserQuestion option offers it". In exactly the case the rule describes, the card can never offer it.
- Not reconfirmed: the stored line file of that session (`~/.local/state/agentview/lines/10ee271c-de52-44dd-85fa-07b140cfbb75.json`) has since been overwritten by a later turn (it now holds n 0 and an empty ask), and no other line file holds that command. The ask text and n 1 are the reporter's account.

**The concierge case:** a boss asks the owner through its concierge, not in its own turn (the guard refuses a boss's own AskUserQuestion while the concierge lives). When the question opens on the concierge's pane, the command in the boss's own line has to be reachable from the boss's card or from the concierge's. Today: not checked. `grep -i concierge` finds nothing in agentview's code (outside `.scratch`), so the roster has no concierge-specific path; which card source applies to the boss's card in that case, and whether the concierge's card shows the boss's ask, was not looked at. The first piece of this work is to look, and to write down what is true.

**Blocked by:** None (can start immediately).

**Claimed by:** Mei 2026-11-10

**Status:** ready-for-human

- [x] A test on `guessed_commands_of` for the question-sourced case: `n` 1 and a stuck with `source "question"` returns the guessed command; `n` 2 still returns none -- evidence: fails on dev before the change, `tests/test_guessed_commands.py`
- [x] The concierge case is checked and written into this ticket (what each card shows with the concierge's question open), and fixed if the command is unreachable there
- [x] A copy button seen on a real card with a dialog open (a session with `n` 1 and a command in its ask, its AskUserQuestion open) -- evidence: screenshot or description of the live card

## Answer (Mei, 2026-11-11)

### The change

`guessed_commands_of` (`fleet.py:1270`) now offers the command for stuck source `"question"` as well as `"line"`, on the same terms: `n` is 1 and `m["blocked"]`, which is true only for a line the session wrote itself this turn (`fleet._shown`, `fleet.py:258`). A line the hook read for the session (`by` not `"session"`) and words read out of the transcript still offer nothing. A permission prompt and another request do not: the first brings its own exact command, the second its own words. `index.html` needed no change: `tile()` renders `guessedBox(t)` under `stuckBox(t)` whatever the stuck source (`index.html:959`).

### Why the old docstring was wrong for this case

It said "an open dialog is shown over it" (the line). That held when a line could be from an earlier moment of the work. It cannot: `hooks/turn_line.py` `begin()` calls `lines.begin_turn` on every UserPromptSubmit, and a cross-session message fires it too (this session's turn from the boss's message got the hook's instruction), so `lines.fresh` (`lines.py:203`) only returns a line written in the turn the session is in. With a question open, that turn is the one that opened the question, and the rule (CLAUDE.md, the hook's own instruction in `hooks/turn_line.py`, paste/10) is that the line is written right before the question with the command after `$ `. So the line with a question open is the line about that question.

**A line older than the question's start.** From an earlier turn: never shown, unchanged (sandbox case E below). From the same turn but written earlier, about something else: shown. There is no reliable moment to compare with: Claude Code writes the AskUserQuestion call into the transcript late, "minutes after the dialog opens, sometimes hours" (`providers/claude.py`, `asking_of` docstring), and the peer record's `statusUpdatedAt` moves with every status change. A time guard would hide the command in the normal case to protect a case the rule already forbids. I added none.

### The concierge case: what each card shows

The protocol (claude-boss 0.22.0): the boss puts the command after `$ ` in its `ASK` message (`skills/boss/references/escalation.md:54`), and the concierge brief ends "A command the owner must run goes on your own session card too, the way your session hooks describe" (`skills/boss/references/concierge-brief.md`, last paragraph). The guard refuses the boss's own AskUserQuestion while its concierge lives, so the dialog is open on the concierge's pane only. agentview has no concierge-specific path: `is_concierge` (`fleet.py:1109`) only adds the tag.

What the concierges actually did, read from the transcripts of the six concierges live on 2026-11-11: 16 of their 53 questions were opened right after their own `team-line --n 1 --ask '... $ <command>'` in the same turn (four concierges, 2026-11-09 20:39 to 2026-11-10 23:00). Each of those 16 had the command in its line and none on its card. So:

- **Concierge's card** (stuck source `"question"`): on dev, never the command, whatever its line says (`fleet.py`, old line 1279). That is where the owner answers. Fixed.
- **Boss's card** (no dialog of its own, stuck source `"line"`): the command when the boss's own line this turn has `n` 1 and the command in its ask; then it showed on dev too. Nothing when the boss's `n` is above 1 (only a count is shown, `need_of`), and nothing once its next turn starts (any worker message starts one) until it writes again.
- **Unreachable from both on dev:** on 2026-11-10 at 00:12 a boss sent an `ASK` with a `bash` command after `$ ` and wrote its own line with `n` 5 and no ask; its concierge wrote `n` 1 with the command and opened the question. The boss card showed "5 answers needed", the concierge card the question, and the command was on neither. With the fix it is on the concierge's card (sandbox case C).
- **Command only on the boss's line** (the concierge left it out of its ask): the boss card shows it when its `n` is 1, on dev and with the fix; the concierge card cannot, since its line does not carry it (case B). Not a defect of the card: the concierge brief asks for it.

### Evidence

Tests (`tests/test_guessed_commands.py`): `test_an_open_question_still_offers_the_command_in_the_line` (`n` 1, source `"question"`, the command), `test_an_open_question_with_several_things_left_offers_nothing` (`n` 2, none), `test_an_open_question_over_a_line_the_hook_read_offers_nothing`, and `test_a_concierge_holding_a_bosss_question_offers_its_command` (concierge-tagged pane). They replace `test_an_open_dialog_hides_the_line_and_its_commands`, which asserted the old behaviour. Run on t-compute (laptop load was 19 to 33): with the fix, `test_guessed_commands test_needs_you test_concierge_tag` 186 tests OK; with dev's `fleet.py` in the same tree, the two command-offering tests FAIL and the rest pass.

The real card: two sandbox servers (this branch on a free port, a `git archive dev` copy on another), both under `env -i` with their own `CLAUDE_CONFIG_DIR`, `XDG_STATE_HOME`, `HOME` and tmux socket under `$XDG_RUNTIME_DIR`, so the real server and tmux never saw them (real tmux: 9 sessions before and after). Each listener's pid was checked against the pid whose `/proc/<pid>/environ` carried the run's marker before every request. Two sessions, a boss "Bramble" and a concierge "Wren" (its pane stamped `@worker_role concierge`, status `waiting`, `input needed`, an unanswered AskUserQuestion in its transcript); each turn begun by the real `hooks/turn_line.py` and each line written by the real `hooks/team-line`.

| Case | Boss line | Concierge line | dev: boss / concierge | fix: boss / concierge |
|---|---|---|---|---|
| A, as the brief asks | n 1, `$ bash ~/maple/push-notes.sh` | n 1, same | command / none | command / command |
| B, command on the boss only | n 1, command | n 1, no command | command / none | command / none |
| C, boss has 2 left | n 2 | n 1, command | none / none | none / command |
| D, concierge n 0 | n 1, command | n 0 | command / none | command / none |
| E, concierge in a new turn, no line yet | n 1, command | (forgotten) | | command / none |

In case A, the page from the fix server (headless Chrome screenshot) shows Wren's card with the CONCIERGE and NEEDS YOU tags, "Question", the question with its two options, and under it a COMMAND row with a copy button and `bash ~/maple/push-notes.sh`. The dev server's page shows the same card without the COMMAND row. Bramble's card shows "1 thing left for you" and the same COMMAND row on both.
