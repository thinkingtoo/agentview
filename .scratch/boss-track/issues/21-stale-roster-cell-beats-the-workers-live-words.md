# 21: A stale roster cell beats the worker's own live words

**What happened:** Yara is building PR 48, her team-line did says so ("PR 48 head c5f7dc6: all review rounds done; only the t-compute suite on that SHA"), but `~/.claude/pm/agentview.md` still has her roster cell "fresh, parked". When she is listed on the objective, the card prints "fresh, parked".

**Cause:** `objectives.workers` takes the table cell first (`table.get(name.casefold())`) and reaches `_own_words` (did, title, prompt) only when the cell is empty. The cell is written by the boss and goes stale the moment a worker is dispatched without the boss rewriting it. Yara is not listed at all right now: her turn is over with a job open, so only PR 48's `watching` admits her.

**Decision (Tarek, boss of agentview, 2026-11-13):** the worker's live did beats a stale cell for the words shown after the name. The cell is the boss's assignment and stays what ties a worker to a ticket and a row; matching keeps reading the cell, and the did where it already does. Reason: the card should show what the worker is doing now, and a cell nobody refreshes lies, as "fresh, parked" did. An idle cell still keeps a worker off the card (PR 47, tested).

**Status:** ready-for-agent, after PR 48 merges (both change `workers()`)

- [ ] A worker with a roster cell and a did shows the did; the cell still decides the ticket it sits on -- evidence: a test in `tests/test_objectives.py`
- [ ] A worker with a cell and no did shows the cell -- evidence: the same class
- [ ] An idle cell still keeps the worker off the card -- evidence: the existing test
