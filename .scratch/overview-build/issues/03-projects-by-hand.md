# 03: Correcting projects by hand

**What to build:** The person can move a session, a whole track or a whole repository into a project, rename a project and merge two, from the page. A move for a track or repository holds for future sessions; a single-session move lasts as long as that session. Stored in `config.json` (`assign` keyed by track or repository as well as by session, `names`).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Moving a repository into a project places a new session from that repository there
- [ ] A single-session move ends with that session
- [ ] Rename and merge survive a restart of the server
- [ ] Covered through `roster()` with a test config
