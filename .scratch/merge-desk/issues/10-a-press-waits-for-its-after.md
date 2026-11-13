# 10: A press of an item with `after: N` waits until N is merged

**What to build:** an item handed over with `--after N` (plan, "What the merge desk holds": "the order it must go in") is pressed only once PR N of the same repo is merged. Pressed earlier, the watcher refuses with "not merged: #N must go in first" and unticks the box, as for any refusal. Found while building 03 (Vera, 2026-11-13): 03 stores `after` but does not enforce it.

**Blocked by:** 03, 04 (both change deskwatch.py; boss, 2026-11-14)

**Status:** ready-for-agent

- [ ] A press of an item whose `after` PR is open is refused with that line, and the box unticks
- [ ] Once N is merged, the same press merges
- [ ] Tests use a fake `gh` on PATH, never the real GitHub
