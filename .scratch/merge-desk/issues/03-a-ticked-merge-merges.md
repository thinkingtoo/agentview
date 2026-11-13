# 03: A ticked Merge merges, at the reviewed commit only

**What to build:** AgentView watches the desk file. A newly ticked Merge item is merged, one at a time in page order: pinned head still current, wait out GitHub's UNKNOWN (60 s, every 2 s), MERGEABLE, then `gh pr merge --merge --match-head-commit`. The result goes under the item; a refusal unticks the box. Every press and result go to `merge-desk.log`. Tonight's temporary server (Kenji's session scratchpad, `merge_server.py`) is the proven reference for these checks.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A branch pushed after the hand-over is refused with "the branch changed after the review", and the box unticks
- [ ] Two presses in a row merge one after the other, never at once
- [ ] UNKNOWN that clears within 60 s merges; one that does not is refused and says so
- [ ] Tests use a fake `gh` on PATH, never the real GitHub
