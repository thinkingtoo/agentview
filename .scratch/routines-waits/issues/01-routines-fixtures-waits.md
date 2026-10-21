# 01: test_routines fixtures lack `waits`

**What to build:** the 3 errors in `tests/test_routines.py` (`Grouping.test_a_project_of_the_same_name_is_not_swallowed`, `Grouping.test_every_routine_comes_after_the_projects_and_none_is_in_a_column`, `Teams.test_a_worker_in_another_project_stays_in_its_own`) are KeyError `m["waits"]` in `fleet.tile_of`. Ticket 21 (8ebee41) added `waits` to the member; the `session()` fixture was not updated.

**Claimed by:** Tarek 2026-10-22 (boss dispatch, task #5, track `paste`)

**Status:** done, merged as e71ec9a

## Decision: stale fixture, not code

`fleet.py` builds `moves` with `"waits": waits_on_a_job(...)` unconditionally and merges it into every member with `**moves`; nothing in a provider's raw record can drop it (`waits_on_a_job` takes only status, tasks, turnOver, all defaulted). Real data always has `waits`. Fix: the fixture.

## Boxes

- [x] `session()` in `tests/test_routines.py` carries waits, bgTasks, call, subFresh, justWrote (all five; ticket 21 added them); tests.test_routines 13 OK
- [x] Full suite on t-compute from git archive of 3822a67: 2195 tests, OK (skipped=4), 0 errors
- [x] Review GO on 3822a67: Opus fallback, Codex unavailable (agentview-wt/reviews/routines-waits-review-1.md)
- [x] Merged to dev as e71ec9a, branch and worktree removed
