# 14: Copy button on commands guessed in the session line

**What to build:** A command a session leaves for the person in its session line (`ask`) gets a copy button too. The session-line hook stays unchanged, so `ask` is free text: the roster guesses the commands in it. Owner's choice, 2026-10-19: "Guess commands in the text": text in quotes, or after a `$`, that reads as a command is offered with a copy button; it will sometimes guess wrong, and that is accepted. A guess never answers the session and never runs anything. Prose without a command shows no button.

**Blocked by:** 07

**Claimed by:** Joaquin 2026-10-19 15:37

**Status:** in-progress

- [ ] The roster reports the guessed commands for a tile's `ask`, tested on invented lines: a quoted command, a `$` command, two commands, and prose with quotes that is not a command (no button)
- [ ] The page shows a copy button per guessed command; copying puts the literal text on the clipboard and sends nothing to the server (smoke on a test server)
- [ ] Markup in a guessed command renders as text (R7)
- [ ] Permission-prompt copy buttons from ticket 07 are unchanged
