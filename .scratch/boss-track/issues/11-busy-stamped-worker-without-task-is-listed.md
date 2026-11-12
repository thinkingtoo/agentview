# 11: A busy stamped worker with no task text is still listed on its track card

**What to build:** a working stamped worker is always listed. The task is, in order: the roster table's cell, the session's own last team-line `did`, its card title (the row carries no "current place" field to add), the first line of its last prompt (all already on the session's row; no transcript is read), else the word "working" so the name still shows. Ticket 06's filter is unchanged: only busy or waiting, no concierge, no boss.

**Why:** the live check after PR 40 (2026-11-12 19:25) missed a busy worker on the Action list card: its tracker's roster is prose, it had written no team-line `did`, so `objectives.workers` found no task and dropped it, the failure Thierry reported (a busy worker not shown). Ticket 07 chose to drop a worker with no line; this reverses that one choice.

**Blocked by:** 06, 07

**Status:** done

- [x] A busy stamped worker with no table row and no `did` is listed, by title, else first prompt line, else "working" -- evidence: `test_objectives.py::Stamped::test_a_busy_stamped_worker_with_no_table_row_and_no_line_is_listed_by_the_best_text_the_server_has`
- [x] The own line wins over the title, the title over the prompt -- evidence: `Stamped::test_the_last_line_wins_over_the_title_and_the_title_over_the_prompt`
- [x] Idle, concierge, other boss's pane: still not listed -- evidence: the unchanged `Stamped` tests
- [x] A table row with an empty task cell falls through -- evidence: `Stamped::test_a_table_row_with_an_empty_task_cell_falls_through_to_the_line_and_the_title`
