# 04: Sessions switch over

**What to build:** sessions stop using the clipboard and leave Pastes instead. The "Clipboard (Proactive Copy)" section in the global CLAUDE.md becomes: leave a Paste for anything the person has to paste, and use the clipboard only when the person asks for it in so many words. The reminder every session gets for `team-line` names the `paste` command and says that a Paste counts in `n`. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** 01 (One Paste end to end), 03 (Secrets in the keyring) — so no session switches over before a token is safe from a plain file.

**Claimed by:** Bruno 2026-10-22 10:02

**Status:** done

- [x] The CLAUDE.md clipboard section is replaced (surgical edit, the rest of the file untouched)
- [x] The `team-line` reminder text names `paste`, how to call it with a file, and that it counts in `n`
- [x] A fresh session, asked to hand over a message, leaves a Paste and does not touch the clipboard (checked once by hand, result written in this ticket's Comments)
- [x] Asked "put it on my clipboard", a session still does

## Comments

- 2026-10-22, Tarek: reminder text merged as eb07911 (tests/test_turn_hook.py, 24 passed; review reviews/paste-04-codex-1.md, Opus fallback, GO). CLAUDE.md section "Clipboard (Leave a Paste)" committed in ~/.claude as 82cc65b (only that section changed).
- Hand check, once, throwaway session 4a770893 (tmux zz-paste04-handcheck, since ended): (a) asked for a short message for a colleague; transcript shows 2 tool calls, a file in the session scratchpad then `hooks/paste create <sid> "$F" --title 'Invoice payment question' --provider claude`, then team-line; no xclip/wl-copy/pbcopy; the clipboard stayed byte-identical to the saved copy; /api/roster showed the Paste (6ac4b3448e8fdaa8, provider claude) on that session's card. (b) "put it on my clipboard": clipboard then held the message and the reply said "Copied to your clipboard." Cleanup: Paste withdrawn, clipboard restored (cmp identical), tmux session killed, no process left.
