# 23: The 🧪 rocks slowly, all the way left and then all the way right

**What to build:** the 🧪 of ticket 18 rocks over 2.4 s instead of 0.9 s, through ±30° instead of ±6°, holding briefly at each end, so it reads as left, then right, not as a jitter.

**Why (Thierry, 2026-11-13, in Italian, on the live card):** "They must rock slower, all the way to the left and then all the way to the right."

**Blocked by:** 18

**Status:** done

- `@keyframes rock`: `rotate(-30deg)` held 0 to 12%, `rotate(30deg)` held 50 to 62%, back to -30deg at 100%; `ease-in-out` between stops; `2400ms`, `transform-origin:50% 50%`. The sideways shift of ticket 18 is gone. Only under `prefers-reduced-motion: no-preference`; otherwise still. Hammers are untouched.
- Room: turned ±30° about its middle, the box reaches about 0.25em past the left of its start. `.ov-obj-line` and `.ov-obj-note`, which clip, get `padding-left:0.3em; margin-left:-0.3em` (the button also `width:calc(100% + 0.3em)`), so the clip box grows and no line moves.
- The redraw carries on at the clock's phase of the 2400 ms cycle.

- [x] The keyframes hold at -30deg and +30deg, nothing else, in a 2400 ms `ease-in-out` cycle gated on motion -- evidence: `tests/test_hammers_on_top.py`
- [x] The clip box is grown on the left and moves nothing; the delay carried on is under 2400 -- evidence: same
- [x] Whole-cycle sweep in the personal Chrome, a page built from this stylesheet at a card's width, 50 ms steps over the 2400 ms cycle: the tilt reaches -30 and +30 with holds; the box keeps 0.06 px to the left of the clip; the box edge overlaps the name's first letter box by 0.43 px (the box is wider than the glyph) and is 2.4 px taller than the line's clip (its ink is not); zooms at -30deg, +30deg and in between show the tube whole and clear of the name -- evidence: PR comment

## Notes

- Suite flake, unexplained: 1 failure in 6 known t-compute runs, test unknown. The first run on f5bf66d (PR 51's head) ended "FAILED (failures=1)" and its output was cut by a `tail`, so the failing test was never named. Two reruns on f5bf66d and three on 6ea51d6 (dev with PRs 50 and 51 merged), each with its full output kept, all ended OK (2503 and 2511 tests, 26 skipped). The run on 68d4c62 was not read. Nothing in PR 51 touches what the suite tests outside the page's CSS. If it recurs, keep the whole output and name the test.
- t-compute has no node, so `tests/test_hammers_on_top.py` skips there (26 skips); run it on the laptop, one file.
