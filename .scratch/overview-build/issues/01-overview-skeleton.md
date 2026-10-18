# 01: Overview skeleton

**What to build:** The main page shows one column per project instead of today's blocks. The roster gains a `columns` list beside today's `blocks` (expand: nothing that reads `blocks` changes). Projects use today's grouping for now. Each column has a plain project card (name only) and one tile per session carrying today's data (name, flag, line, jump). Columns keep a 230 px minimum width and scroll sideways. The chime, search, closed and reopen keep working untouched. This is the tracer bullet every other ticket builds on; see the build spec's roster contract.

**Blocked by:** None (can start immediately)

**Claimed by:** Joaquin 2026-10-19 00:03

**Status:** done

- [x] `roster()` returns `columns` in display order next to the unchanged `blocks`; tested with fake providers
- [x] The page renders columns from `columns` only, with no grouping or ordering logic in the browser
- [x] Columns never change each other's height; with more projects than fit, the page scrolls sideways
- [x] The chime still rings on `waiting`, and search, closed and reopen behave as before (smoke run by hand)

**Evidence (Joaquin, 2026-10-19, branch `overview/01-skeleton`, final head 98ef823; Mistral GO on that head; Status `done` on the boss's merge order):**

1. `tests/test_columns.py` (24, through `roster()` with the `Fake` provider) and `tests/test_roster_route.py` (2, real handler on a port-0 server). Full suite `XDG_STATE_HOME=<scratch> python3 -m unittest discover -s tests`: 598 tests, OK (skipped=1) on the final tree. Three runs on the earlier head 7a2a306: two OK, one failed on `test_scope_check.Scopes.test_a_process_is_ours_only_if_its_own_environment_says_so` (tests/test_scope_check.py:583), the known pre-existing flake; the branch touches neither that test nor `scripts/scope-check`, and 0 of 150 isolated runs failed on the branch and on the dev checkout.
2. Smoke "columns in the order the server sent, not the blocks' or a sort" (fixture: blocks reversed with a routine block, columns in a non-alphabetical order) and "the routine block is not a column"; unrouted pass: DOM column and tile counts equal `COLUMNS` read from the test server's own roster.
3. Smoke: every column at least 230 px; a column given 12 more tiles leaves its neighbour's offsetHeight unchanged; with ten projects `main` scrolls sideways (`scrollWidth > clientWidth`, `overflow-x: auto`) and the page does not; a repaint keeps `scrollLeft`.
4. Smoke (routed): chime rings once on a new `waiting`, not again, mute posts `/api/chime`, tick on `ready`, question beats tick, tone and blip rendered offline (overview); the ring check also on `?view=blocks`; filter, closed list (`/api/revive`), search and reopen (`/api/reopen`, running one jumps) all fulfilled by `page.route`. Final-tree command: `python3 tests/ui_smoke.py http://127.0.0.1:33257/ <test config> 408085` -> 122 checks OK, "all green", exit 0 (test server on a port-0 free port, listener pid proven with `ss` before the run). Live `config.json` sha256 before and after: `769cd744b9dbcb57e3e749af216faa2156b52185115194b43fec4409d35fc802` both.
5. Code review (`mattpocock-skills:code-review`, Standards and Spec axes): no hard standards violation. One real gap fixed, tests first: a session with `blocked` rings the chime but its tile showed no reason; the tile now carries `blocked` and `need` and the page prints the need line (4 new tests). README describes the overview and marks the old controls as block-view only.
6. History check on `git log -p dev..HEAD` and commit messages against archive.db titles and prompt openings (read-only) and the client folder names: one invented fixture name hit the archive and was renamed inside the page commit before anything left the machine; afterwards 0 name-like new strings hit titles, prompt openings or client folders.
7. Mistral (`mistral-large-latest`, `/home/tiroir/Projects/agentview-wt/mistral-review.py`), review files in `/home/tiroir/Projects/agentview-wt/reviews/`: `mistral-review-01-1.md` NO-GO, `mistral-review-01-2.md` NO-GO (four findings in all, citations verified, none a bug; replies in `replies-01-2.md`, `replies-01-3.md`), `mistral-review-01-3.md` **VERDICT: GO on head 98ef8238c6332c2f7b62b9619257a8fbceb45cf9**. The code did not change between the three rounds.
