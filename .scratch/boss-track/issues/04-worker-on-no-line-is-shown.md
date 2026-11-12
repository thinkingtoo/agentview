# 04: A worker whose task ties to no line shows nowhere on the card

**What to build:** a live roster worker whose task no row's ticket carries is listed under the rows as `🔨 <Name>: <roster task>`. Hammers stay tied to `feature/NN` refs (ticket 01); bare numbers are not guessed onto a feature.

**Why (Thierry, 2026-11-12):** "On the codex-down card only one line is ticked and all the others are 'planned', yet I see 2 agents green, so they are working on an issue? There should be a hammer showing what they work on."

**Diagnosis (read 2026-11-12, Maja):**
- The service runs the feature: `agentview.service` ActiveEnter 01:41:03 CET, merge b35dff1 01:40:44; live `/api/roster` has `track.rows` for Codex down (12 rows, 1 done). Not stale, no parse failure.
- All 12 rows have `tickets: []`. `objectives.REF` only reads `<feature>/<NN>`; a worker is joined to a row only when `refs_in(task)` meets `refs_in(line)`. codex-down's lines say `01 (PR #11 …)`, `(ex-02, coverage.md)`, `(ex-05 …)`; its roster tasks say `#09c waiver + consent token` (Rosalie) and `#26 owner-choice edge cases` (Otilia). Neither side has a `feature/NN`, so no row can be `worked`.
- The 09c/26 to line map exists only in `/home/tiroir/Projects/boss-plugin/.scratch/codex-down/coverage.md`, and ticket files 09c/26 are not in `.scratch/codex-down/issues` (01-12 only). coverage.md is not read: its layout is codex-down's own (R-numbers to boxes), agentview cannot rely on it for every track; a guessed link would put a hammer on the wrong line.

**Roster state read:** the `Roster` tables of `~/.claude/pm/<track>.md` (`projects.roster_tasks`) joined with the track's live sessions. A struck-through row is retired and an empty or `idle`/`free`/`none`/dash task is idle: neither is listed. A worker already on a row's ticket is not listed again.

**Blocked by:** 01

**Status:** done

- [x] A live worker with a task tying to no line is listed with name and task -- evidence: `test_objectives.py::test_a_live_worker_whose_task_ties_to_no_line_is_shown_with_its_task`
- [x] Retired, idle, absent-session workers listed nowhere; a worker on a hammer row is not listed twice -- evidence: `test_a_worker_gone_or_struck_through_or_with_no_task_is_not_shown_elsewhere` and the first test (Odile)
