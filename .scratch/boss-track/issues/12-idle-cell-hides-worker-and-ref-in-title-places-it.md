# 12: A table cell saying idle hides a working worker; a ticket ref in a title or prompt can place one

**What to build:** decide, and pin with tests, two edges left by ticket 11 (class c, found in its review, left on purpose):

- A busy stamped worker whose Roster table cell says `idle`, `-`, `free` or `none` is not listed: the cell wins over the stamp and `objectives.elsewhere` drops it as idle. Decide whether a working session should beat an idle-looking cell.
- `objectives.rows` reads ticket refs out of every crew task, so a ticket ref (`feature/12`) in a worker's card title or the first line of its prompt, now a task source, can hammer that ticket's row. Decide whether only the table cell and the worker's own line may place a worker.

**Why:** ticket 11 made the card list every working stamped worker; these two cases were judged far-fetched or deliberate in the PR 43 review (comments there) and left as they are.

**Blocked by:** None

**Status:** needs-triage

- [ ] Each edge decided, with a test pinning the decision
