# 18: A worker watching its own jobs keeps a still hammer on its objective

**What to build:** a crew worker whose turn is over but who has a background job of its own open (`waits`) is listed like a working one: its hammer is on its row, or in `elsewhere` when no row's ticket carries its task, and it stays still.

**Why (Thierry, 2026-11-13 00:55, in Italian):** "But she's working on an objective, no? Her test is tied to an objective. The card should show that Naya is watching the tests for that objective." Live case: Naya (idle, ready, "2 background jobs", her own pytest running) had no hammer anywhere on the action-list card.

**Blocked by:** 17

**Status:** done

- `objectives.workers` admits a session that is `working` (ticket 06) or `watching` (`waits`). `busy_names` is untouched, so the hammer is not busy: still.
- A row whose workers all watch jobs is state `worked` (🔨 still), not `waiting` (⏸, which stays for a row blocked by an open ticket).
- Idle with no job, a boss and a concierge stay out. A roster cell that says idle still wins.
- No new sign.
- Matching is not widened. Naya's words (`private-root-4 / #467`, no Roster table, only the claude-boss stamp) carry no `feature/NN`, so she lands in `elsewhere`, not on the row "Stages 1, 2, 3 of #467 applied on tiroir-tt…". Whether `#467` should tie is a separate ticket.

- [x] Idle with a job open and a roster task: row worked, not busy, worker listed on the ticket -- evidence: `tests/test_objectives.py` (class `Watching`)
- [x] A row whose workers all watch jobs is worked; one busy beside a watching one swings the row -- evidence: same
- [x] Idle with no job, a concierge and a boss with a job stay out -- evidence: same
- [x] A stamped worker watching a job, with no ref in its words, is in `elsewhere`, still -- evidence: `tests/test_objectives.py` (class `Stamped`)
