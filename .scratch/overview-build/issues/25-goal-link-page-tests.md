# 25: Page tests for the goal link's branches on a track card

**What to build:** `tests/ui_smoke.py` checks for the track card from ticket 23: "goal ↗" with its href and `target=_blank` on a page at 127.0.0.1; "goal on the laptop" on any other host (`localhost`, a tailscale name); "no goal page" with the server's reason in the hover when `track.goal.url` is null; "N of M" unfolding and folding the Done when boxes, the unfold surviving a repaint; and box text and the goal's reason given as markup (`<svg onload=...>`) shown as text. Use a fake roster body, as the smoke does for other cards.

**Why:** found by the spec review and by the final review run on PR #6. The server side is tested (`tests/test_goal_page.py`, `tests/test_context.py`), but no test covers `goalLinkOf`, `boxesOf` or `ON_THE_LAPTOP` in index.html. They were checked by hand on a sandboxed server only.

**Where:** `tests/ui_smoke.py`; `index.html` `goalLinkOf`, `boxesOf`, `progressOf`.

**Blocked by:** None.

**Claimed by:** Tarek 2026-11-11

**Status:** needs-triage

- [ ] Each branch above has a check in ui_smoke, and each check fails when its branch is removed from index.html -- evidence: the smoke output, and one mutation per branch
