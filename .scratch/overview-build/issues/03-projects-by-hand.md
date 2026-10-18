# 03: Correcting projects by hand

**What to build:** The person can move a session, a whole track or a whole repository into a project, rename a project and merge two, from the page. Each project card has a pin button: pinned projects lead in the order they were pinned, with left/right arrows on pinned cards to reorder and the pin again to unpin (owner, 2026-10-19). A move for a track or repository holds for future sessions; a single-session move lasts as long as that session. Stored in `config.json` (`assign` keyed by track or repository as well as by session, `names`).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Moving a repository into a project places a new session from that repository there
- [ ] A single-session move ends with that session
- [ ] Rename and merge survive a restart of the server
- [ ] Pinning, reordering and unpinning a project from its card is stored in `pinned` and orders the columns (roster test plus smoke run)
- [ ] Covered through `roster()` with a test config
