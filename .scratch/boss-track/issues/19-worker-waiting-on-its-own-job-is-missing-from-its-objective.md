# 19: A worker that waits on its own job is missing from its objective

**What happened (Thierry, 2026-11-13 01:12, phone screenshot):** Vera, busy on codex-down ticket 40, showed no hammer. `/api/roster` codex-down had `elsewhere: []` and no worked row. Otilia, on the same team, did show.

**Cause:** `objectives.working()` is false for any session with `waits` set (a turn over with a Monitor, shell or background job open, ticket boss-track/06). `objectives.workers()` admits only `working()` sessions, so a stamped worker with a roster cell, a name and a pane owner that is all correct is dropped while she waits on her review and CI. Vera's own line at 01:13 was "wacht op Opus-review en CI". Otilia's turn was in flight, so she passed. The stamp read (`_read_panes`), the rename Nour to Vera and the roster-cell parse are not at fault: at 01:17, with her turn running, Vera was listed with the same cell, pane and stamp (`elsewhere: [Vera, busy]`).

**Evidence:** `workers("codex-down", [Vera busy, waits False], ...)` returns Vera; with `waits True` it returns `{}` (scratch repro, 2026-11-13 01:20). Her `waits` at 01:13 was not recorded, so the link between her state then and the empty list rests on this repro and her line, not on a captured session file.

**Fixed by:** PR 48 (boss-track/18): `workers` admits a `watching` session. This ticket adds nothing to production.

**Status:** done when PR 48 merges

- [ ] A stamped worker with a roster task, busy with a job open, is listed with that task and carries the 🧪 sign -- evidence: a test in `tests/test_objectives.py` (class `Watching`)
