# 17: A Codex session that waits on you rings the chime

**What to build:** when a Codex session escalates a command and waits for approval, the overview shows Needs you on the tile, the header and the tab, but the chime stays silent: Codex has no `waiting` flag, and the README says a Codex row never rings. The owner decided on 2026-10-20 that it rings: a Codex row that turns Needs you rings the same two-stroke chime as a waiting Claude session, once per new wait, and never again for the same wait on later polls. Change the README sentence to say what is now true.

**Blocked by:** 12, 13

**Claimed by:** Joaquin 2026-10-20

**Status:** ready-for-agent

- [ ] Tests: a Codex row that turns Needs you rings once; the same wait on later polls does not ring again; a new wait after it ends rings again; a Codex row that is busy or idle never rings; Claude rows ring as before
- [ ] The smoke covers a Codex row turning Needs you and the chime firing once, against a test server
- [ ] The README describes the Codex ring, and no sentence there still says a Codex row never rings
- [ ] Hostile text in the Codex command renders as text (R7)
