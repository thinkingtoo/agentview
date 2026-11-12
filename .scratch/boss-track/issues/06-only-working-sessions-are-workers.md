# 06: Only a session that is working counts as a worker on a track card

**What to build:** the hammer on a row and the `🔨 Name: task` list under the rows (ticket 04) name a session only when it is working now. A concierge and an idle session are not workers.

**Why (Thierry, 2026-11-12):** the elsewhere list showed concierges ("concierge") and sessions whose task read "#10 MERGED … Done, idle", because the roster task text was the only test.

**Which states count, from the state the server holds per session (`status`, `waits`, the pane marks):**
- `busy`: counts. It is on a turn.
- `waiting` (a dialog is open): counts. The turn is not over; it waits on a person, and the card should say what it is on.
- `idle`: never. A parked or merged worker is on nothing, whatever its roster row still says.
- `shell`: never. The provider maps it to `idle` with a job still running (`providers/claude.py`, `bg`); the status flips to `busy` when a turn starts, so a shell session with its turn in flight is already `busy`. The server has no second signal for it, and needs none.
- busy but `waits` (turn over, a background job runs on): does not count; that is waiting on a job, not work (ticket 20 of the overview).
- A concierge never counts: its pane carries `@worker_role concierge` (read by `fleet._pane_roles`), or its roster task says "concierge" (the mark is lost on a reboot).
- The boss is never a worker.

**Blocked by:** 04

**Status:** done

- [x] Idle, `shell` and `waiting`-on-a-job sessions: no hammer, not listed -- evidence: `test_objectives.py::Working::test_an_idle_or_shell_worker_is_on_no_line_and_not_elsewhere`
- [x] Busy and waiting sessions count -- evidence: `Working::test_a_waiting_session_is_working_and_so_is_a_busy_one`
- [x] Concierge by pane mark or by task -- evidence: `Working::test_a_concierge_is_never_a_worker_by_its_pane_mark_or_by_its_task`
- [x] A card shaped on the live insights-bento one lists only the busy worker -- evidence: `Working::test_a_card_shaped_on_the_live_one_lists_only_the_busy_worker`
