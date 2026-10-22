# 04: Sessions switch over

**What to build:** sessions stop using the clipboard and leave Pastes instead. The "Clipboard (Proactive Copy)" section in the global CLAUDE.md becomes: leave a Paste for anything the person has to paste, and use the clipboard only when the person asks for it in so many words. The reminder every session gets for `team-line` names the `paste` command and says that a Paste counts in `n`. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** 01 (One Paste end to end), 03 (Secrets in the keyring) — so no session switches over before a token is safe from a plain file.

**Claimed by:** Bruno 2026-10-22 10:02

**Status:** in-progress

- [ ] The CLAUDE.md clipboard section is replaced (surgical edit, the rest of the file untouched)
- [ ] The `team-line` reminder text names `paste`, how to call it with a file, and that it counts in `n`
- [ ] A fresh session, asked to hand over a message, leaves a Paste and does not touch the clipboard (checked once by hand, result written in this ticket's Comments)
- [ ] Asked "put it on my clipboard", a session still does
