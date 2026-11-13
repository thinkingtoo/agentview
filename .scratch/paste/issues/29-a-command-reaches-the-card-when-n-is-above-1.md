# 29: A command to run reaches the card when more than one thing waits

**What to fix:** `hooks/team-line` keeps `--ask` only when `--n` is 1 (`ask = said if args.n == 1 else ""`, team-line line 30). A boss whose question sits in its concierge's pane, with n > 1 (a question and a Paste, say), therefore has no way to put the command from that question on its own card as a button: the concierge's card shows the open question, the boss's card shows only `did`. Give team-line a supported way to carry one command when n > 1 (for instance a `--cmd '<command>'` that renders as the command button whatever n is), and say in the hook's instruction text when to use it.

**Seen:** 2026-11-13, tt-arch (boss Dmitri, session d3c1cf39-fae7-4d5c-b79c-22e4b3f06592): `--n 2` with no ask, then `--n 1` with an ask naming the Paste instead of `$ <command>`; Thierry ran a paid command by hand with no button on the card. Reported to Tarek by Dmitri.

- [ ] With n = 2 and a command given, the card shows the command button and the count 2
- [ ] With n = 1 the existing `$ ` ask keeps working unchanged
- [ ] The UserPromptSubmit instruction text says how to give the command when n > 1

**Blocked by:** None.

**Status:** needs-triage
