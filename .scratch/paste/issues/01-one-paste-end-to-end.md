# 01: One Paste end to end

**What to build:** a session leaves a titled text on its card with the new `paste` command, reading the text from a file. The person sees the title and first line on the session's card, opens the full text, copies it exactly with the copy button, and ticks it done. Copying keeps it; done removes it. The session can withdraw a Paste by the id the command printed. Several Pastes can wait on one session. The glossary gets the term **Paste**. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** None (can start immediately).

**Claimed by:** Ines 2026-10-21 22:42

**Status:** in-progress

- [ ] The command creates a Paste from a file and prints its id; missing, empty or oversized files are refused with a non-zero exit and nothing written
- [ ] `/api/roster` lists a session's Pastes (id, title, first line, copied flag) without their full text
- [ ] The full text comes back byte-identical through its own route, including quotes, backslashes, tabs and blank lines
- [ ] Copy marks the Paste copied and keeps it; done removes it; withdraw by id removes it
- [ ] Several Pastes on one session all show, in the order they were made
- [ ] The card shows title + first line + copy + done; clicking the title opens the full text (UI smoke test)
- [ ] The store sits beside the session lines, never under `~/.claude` or anything brain-sync carries
- [ ] GLOSSARY.md has the entry **Paste**, with "draft, clipboard item, handout" under Avoid
- [ ] Tests go through the command + roster seam with a fake provider and a throwaway store, as the notes route tests do
