# 02: Project assignment

**What to build:** Each session lands in the project the person thinks of it as. First match wins: the person's own setting; the boss track (a worker by its tmux track, then `reportsTo`, then the single tracker naming it; a boss by its marker), which spans repositories; the repository keyed by remote, with worktrees folded onto their parent and each client folder its own project; today's folder rule; otherwise the guess, into a last No project column with a one-click suggestion. The launch folder fixes the project for rules 3 and 4. A boss shows once, first in its column. Column order: pinned projects in the person's order, then other tracks, then repositories, then No project. Systemd routines are no longer shown (decided 2026-10-18).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A worker in another repository than its boss sits in the boss's track column
- [ ] Two worktrees of one repository share one column; two client folders never do
- [ ] A session that `cd`s elsewhere keeps its column
- [ ] Pinned columns lead in pinned order; No project is last; routines do not appear
- [ ] Disagreeing boss signals resolve as the design spec orders them; all covered through `roster()` with fake providers
