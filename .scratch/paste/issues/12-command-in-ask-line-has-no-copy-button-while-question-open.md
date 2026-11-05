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

**Claimed by:** none

**Status:** needs-triage

- [ ] A test on `guessed_commands_of` for the question-sourced case: `n` 1 and a stuck with `source "question"` returns the guessed command; `n` 2 still returns none -- evidence: fails on dev before the change, `tests/test_guessed_commands.py`
- [ ] The concierge case is checked and written into this ticket (what each card shows with the concierge's question open), and fixed if the command is unreachable there
- [ ] A copy button seen on a real card with a dialog open (a session with `n` 1 and a command in its ask, its AskUserQuestion open) -- evidence: screenshot or description of the live card
