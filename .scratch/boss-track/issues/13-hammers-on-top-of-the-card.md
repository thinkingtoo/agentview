# 13: Every hammer on a track card sits on top, above waiting, planned and done

**What to build:** the `🔨 Name: task` lines for workers on no row (`track.elsewhere`, tickets 04, 07, 11) are drawn right after the worked rows and before the waiting, planned and done rows, so all hammers sit together at the top. The fold ("N of M"), the click on a row and the non-clickable class of the elsewhere lines (ticket 04) are unchanged.

**Why (Thierry, 2026-11-12):** "active (hammers) on top of the list, I thought that sort rule was given". It was: ticket 01 sorts rows worked, waiting, planned, done (his Q9, "active first"). But the elsewhere lines were drawn below every row: on the Action list card, Anika's hammer came after 7 planned and 5 done rows.

**Blocked by:** 01, 04

**Status:** done

- [x] The elsewhere lines come after the worked rows and before the rest; with no worked row they come first; several stay together -- evidence: `tests/test_hammers_on_top.py` (runs the real `doneWhenOf()` from index.html under node)
- [x] Rows keep their button and `data-row`; the elsewhere lines have none; markup in a name or task builds no element -- evidence: same file
- [x] `ui_smoke` has no `track.elsewhere` fixture, so it holds no order check to update; the order check in the browser belongs to ticket 05 (needs-triage) -- evidence: `grep elsewhere tests/ui_smoke.py` finds only a column named "Elsewhere"
