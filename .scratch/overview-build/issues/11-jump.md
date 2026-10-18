# 11: Jump to background sessions and no terminal

**What to build:** One click reaches every session. A background session opens in a new WezTerm tab running `claude attach` on it. A session with no terminal is known before the click and shows "no terminal" greyed in place of the jump. A failed jump leaves its reason on the tile until the next poll. The page never opens a second copy of a running session.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The pure route chooser returns an attach route for a background session (tested like today's routes)
- [ ] The roster reports jump as pane, attach or none with a reason
- [ ] A failed jump's reason shows on the tile
