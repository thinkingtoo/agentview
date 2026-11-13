# 21: A stale roster cell beats the worker's own live words

**What happened:** Yara is building PR 48, her team-line did says so ("PR 48 head c5f7dc6: all review rounds done; only the t-compute suite on that SHA"), but `~/.claude/pm/agentview.md` still has her roster cell "fresh, parked". When she is listed on the objective, the card prints "fresh, parked".

**Cause:** `objectives.workers` takes the table cell first (`table.get(name.casefold())`) and reaches `_own_words` (did, title, prompt) only when the cell is empty. The cell is written by the boss and goes stale the moment a worker is dispatched without the boss rewriting it. Yara is not listed at all right now: her turn is over with a job open, so only PR 48's `watching` admits her.

**Decision (Tarek, boss of agentview, 2026-11-13):** the worker's live did beats a stale cell for the words shown after the name. The cell is the boss's assignment and stays what ties a worker to a ticket and a row; matching keeps reading the cell, and the did where it already does. Reason: the card should show what the worker is doing now, and a cell nobody refreshes lies, as "fresh, parked" did. An idle cell still keeps a worker off the card (PR 47, tested).

**Status:** done

- [x] A worker with a roster cell and a did shows the did; the cell still decides the ticket it sits on -- evidence: `tests/test_objectives.py` class `Stamped` (three tests naming ticket boss-track/21)
- [x] A worker with a cell and no did shows the cell -- evidence: the same first test (Odile)
- [x] An idle cell still keeps the worker off the card -- evidence: `test_an_idle_cell_keeps_the_worker_off_the_card_even_with_a_line`

**Known limit (Codex review 1):** a worker's `did` stays until it writes another (`lines.kept_did`). If the boss rewrites the cell to a new task that sits on no row, the card prints the old did until the worker runs its team-line again. That follows from the decision as written; a worker that never updates its line is the source, not this code.
