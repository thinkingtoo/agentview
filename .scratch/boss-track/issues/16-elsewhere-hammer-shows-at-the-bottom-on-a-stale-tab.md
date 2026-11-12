# 16: The elsewhere hammer on the codex-down card shows at the bottom

**What to build:** find why Thierry saw the `🔨` of a worker on no row at the bottom of the codex-down card, when `doneWhenOf()` puts it first on a card with no worked row (ticket 13), and fix the cause.

**Why (Thierry, 2026-11-12, in Italian):** "on the Codex Down card there's a hammer all alone at the very bottom; by the logical order it should be at the top." Live at 19:58: `/api/roster` codex-down had 0 worked rows, 3 planned, 9 done, and `elsewhere` held one worker.

**Blocked by:** 13

**Status:** done

## Finding

- Rendered by the current build (hash `8a4a1e1f0788`) in the personal Chrome: the `ul.ov-objs` of the codex-down card starts with the `st-worked` elsewhere `<li>` (top 484 px), then the 3 planned rows, then the 9 done. No CSS `order`, no other render path (`grep elsewhere index.html`: only `elsewhereOf` and its one use in `doneWhenOf`); a folded card renders nothing, not the list at the bottom.
- Ticket 13 (the hammers go on top) reached `index.html` at 19:36:27; before it the elsewhere `<li>` was appended after every row, which is exactly what he saw. The reload-on-new-build (`c707210`, 19:27:11) exists only in pages loaded after it; a tab opened before 19:27 has no code that reloads it, so it keeps drawing the old order for good.
- Not reproducible on the current page; the stale tab is the cause the evidence leaves. His own tab was not inspectable from here.

- [x] The live shape (no worked row, 3 planned, 9 done, one elsewhere) draws the hammer first -- evidence: `tests/test_hammers_on_top.py` (passes before and after: the code was right, the tab was old)
- [x] Nothing to change in the page: a reload of the tab shows the hammer on top -- evidence: the live DOM read in the personal Chrome (first `<li>` is `st-worked`, top 484 px) and before/after screenshots, reported to the boss
