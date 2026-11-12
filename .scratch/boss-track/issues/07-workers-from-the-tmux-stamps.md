# 07: A track's workers from the tmux stamps when the tracker has no table for them

**What to build:** the workers of a track are the working sessions whose pane carries `@boss_pane` = the pane of the track's boss, with the roster table's task when the table names them, else the line (`did`) the session last wrote on its card, else nothing (then it is shown nowhere). A tracker with a table works as before.

**Why:** action-list's roster is prose and chat-box's live roster is a prose line under an empty table, so `projects.roster_tasks` finds nobody and neither card shows a hammer or an elsewhere line, although their bosses have busy workers (diagnosis 2026-11-12). Parsing the prose would guess names and tasks apart; the stamps claude-boss writes on every pane it spawns or claims say who owns whom.

**How it is read:** `fleet._read_panes` extends the one `tmux list-panes -a` the concierge tag already ran, at most once per 5 seconds, with `#{@boss_pane}`; no extra call, none per request. The boss of a track is the session `projects.boss_tracks` gives the track (its marker), and its pane is the pane id in its `tmux` field. No tmux or no server: no stamps, and the table path is all there is.

**Blocked by:** 06

**Status:** done

- [x] A prose roster beside an empty table: a stamped worker's line gives the hammer or the elsewhere entry -- evidence: `test_objectives.py::Stamped::test_a_worker_on_a_prose_roster_is_shown_with_what_it_last_said_and_hammers_its_line`
- [x] The table's task wins; a session outside the table needs a stamp -- evidence: `Stamped::test_the_tables_task_wins_over_the_last_line_and_a_session_outside_the_table_needs_a_stamp`
- [x] A pane stamped to another boss, a concierge, an idle worker, a worker with no line: not listed -- evidence: the other three `Stamped` tests

## Comments

- 2026-11-12: ticket 11 reversed "shown nowhere": a working stamped worker with no line is listed by its card title, its prompt's first line, or "working".
