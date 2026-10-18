# 01: Overview skeleton

**What to build:** The main page shows one column per project instead of today's blocks. The roster gains a `columns` list beside today's `blocks` (expand: nothing that reads `blocks` changes). Projects use today's grouping for now. Each column has a plain project card (name only) and one tile per session carrying today's data (name, flag, line, jump). Columns keep a 230 px minimum width and scroll sideways. The chime, search, closed and reopen keep working untouched. This is the tracer bullet every other ticket builds on; see the build spec's roster contract.

**Blocked by:** None (can start immediately)

**Claimed by:** Joaquin 2026-10-19 00:03

**Status:** in-progress

- [x] `roster()` returns `columns` in display order next to the unchanged `blocks`; tested with fake providers
- [x] The page renders columns from `columns` only, with no grouping or ordering logic in the browser
- [x] Columns never change each other's height; with more projects than fit, the page scrolls sideways
- [x] The chime still rings on `waiting`, and search, closed and reopen behave as before (smoke run by hand)

**Evidence (Joaquin, 2026-10-19, branch `overview/01-skeleton`, head 7a2a306; review, Codex and the history check are still to do, so Status stays in-progress):**

1. `tests/test_columns.py` (20, through `roster()` with the `Fake` provider) and `tests/test_roster_route.py` (2, real handler on a port-0 server). Full suite `XDG_STATE_HOME=<scratch> python3 -m unittest discover -s tests`: 594 tests, OK (skipped=1) on six consecutive runs; one earlier run failed once and its test name was not captured (the noted `test_scope_check` flake is the known candidate).
2. Smoke "columns in the order the server sent, not the blocks' or a sort" (fixture: blocks reversed with a routine block, columns in a non-alphabetical order) and "the routine block is not a column"; unrouted pass: DOM column and tile counts equal `COLUMNS` (14 columns, 21 tiles on the test server's real roster).
3. Smoke: every column at least 230 px; a column given 12 more tiles leaves its neighbour's offsetHeight unchanged; with ten projects `main` scrolls sideways (`scrollWidth > clientWidth`, `overflow-x: auto`) and the page does not; a repaint keeps `scrollLeft`.
4. Smoke (routed): chime rings once on a new `waiting`, not again, mute posts `/api/chime`, tick on `ready`, question beats tick, tone and blip rendered offline (overview); the ring check also on `?view=blocks`; filter, closed list (`/api/revive`), search and reopen (`/api/reopen`, running one jumps) all fulfilled by `page.route`. Command: `python3 tests/ui_smoke.py http://127.0.0.1:33417/ <test config> 312952` -> 121 checks OK, exit 0. Live `config.json` sha256 before and after: `769cd744b9dbcb57e3e749af216faa2156b52185115194b43fec4409d35fc802` both.
