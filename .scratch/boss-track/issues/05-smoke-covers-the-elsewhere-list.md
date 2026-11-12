# 05: ui_smoke does not cover the elsewhere list

**What to build:** a check in `tests/ui_smoke.py` that the track card's "also working on" list (ticket 04, `track.elsewhere`) renders each worker as name and task through `esc()`, and that a click on it leaves every row's `aria-expanded` unchanged and adds nothing to `OPEN_ROWS`. Pins the fix of PR 35 (the list once shared the row-toggle class). Runs on t-compute only.

**Why:** found in the second review round of PR 35 (Maja, 2026-11-12): the `ui_smoke` fixture has no `track.elsewhere` data, so no test would catch the list taking the row-toggle class again.

**Blocked by:** 04

**Status:** needs-triage

- [ ] The list renders in the routed fixture with markup in a name and a task building no element -- evidence: `ui_smoke` check, green on t-compute
- [ ] A click on the list leaves every `aria-expanded` unchanged -- evidence: same check, red with the class put back to `ov-obj-line`
