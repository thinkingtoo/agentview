# 18: A worker watching its own jobs shows a rocking 🧪 on its objective

**What to build:** a crew worker whose turn is over but who has a background job of its own open (`waits`) is listed like a working one, with the sign 🧪 on its row, or in `elsewhere` when no row's ticket carries its task.

**Why (Thierry, 2026-11-13 00:55, in Italian; then "Per i test 🧪" and "Oscillante destra sinistra"):** "But she's working on an objective, no? Her test is tied to an objective. The card should show that Naya is watching the tests for that objective." Live case: Naya (idle, ready, "2 background jobs", her own pytest running) had no hammer anywhere on the action-list card.

**Blocked by:** 17

**Status:** done

- `objectives.workers` admits a session that is `working` (ticket 06) or `watching` (`waits`). `busy_names` is untouched, so it is never busy. `watching_names` names them; `rows[].watching` and `elsewhere[].watching` carry it.
- The signs: swinging 🔨 = turn in flight; still 🔨 = a question open; rocking 🧪 = own jobs running; ⏸ = a row waiting on someone else. A row with several workers shows the strongest: swinging, then still 🔨, then 🧪 (`watching` is true only when every worker on the row watches). An `elsewhere` entry has its own sign.
- 🧪 rocks (`@keyframes rock`, 900 ms, a tilt plus a shift to the right only, so the line never clips it), only under `prefers-reduced-motion: no-preference`; otherwise it is still. Every background job gets 🧪: the task's `label` is free text, so telling tests apart would be a guess, and it is not built.
- A row whose workers all watch jobs is state `worked`, not `waiting` (⏸, which stays for a row blocked by an open ticket).
- Idle with no job, a boss and a concierge stay out. A roster cell that says idle still wins.
- Matching is not widened. Naya's words (`private-root-4 / #467`, no Roster table, only the claude-boss stamp) carry no `feature/NN`, so she lands in `elsewhere`, not on the row "Stages 1, 2, 3 of #467 applied on tiroir-tt…". Whether `#467` should tie is a separate ticket.

- [x] Idle with a job open and a roster task: row worked, not busy, worker listed on the ticket -- evidence: `tests/test_objectives.py` (class `Watching`)
- [x] A row whose workers all watch jobs is worked; one busy beside a watching one swings the row -- evidence: same
- [x] Idle with no job, a concierge and a boss with a job stay out -- evidence: same
- [x] A stamped worker watching a job, with no ref in its words, is in `elsewhere`, still -- evidence: `tests/test_objectives.py` (class `Stamped`)
- [x] `watching` is true on a row only when every worker on it watches; a busy or question-open worker beats it -- evidence: `tests/test_objectives.py` (`Watching`)
- [x] The page draws 🧪 with `rock` for a watching row or entry, the hammer otherwise; `rock` lives only under `no-preference` -- evidence: `tests/test_hammers_on_top.py`
