# 28: A Paste whose text is one shell command gets the command button

**What to fix:** a Paste whose whole text is a single shell command renders today as a Paste (title, first line, open to copy). The person has to open it and copy it. Render it with the same command button an ask's `$ <command>` line gets (copy without the `!`, as `ask_commands` does), so a hand-run command is one press away on the card.

**Seen:** 2026-11-13, tt-arch (boss Dmitri, session d3c1cf39-fae7-4d5c-b79c-22e4b3f06592): Paste 939b140af4a3af07 "Recheck run (EUR 3 stop)", a paid command Thierry had to run by hand; the card offered no button for it. Reported to Tarek (merge-desk boss) by Dmitri.

- [ ] A Paste of exactly one command line (no newline, after trim) shows the command button; a multi-line or prose Paste stays as today
- [ ] A secret Paste never gets the button (its text is not on the page)
- [ ] The button copies the command exactly, with no leading `!`

**Blocked by:** None.

**Status:** needs-triage
