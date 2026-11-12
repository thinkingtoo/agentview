# 03: The card's about text is clipped at three lines and a tap shows it whole

**What to build:** the card's context line (a track's whole Outcome, a README paragraph, your own line) shows at most three lines, with an ellipsis when it is longer. Hover does not exist on the phone, so a tap or click on a clipped text shows it whole; a "less" at its end clips it again. A text that is not clipped (or is unfolded) keeps today's click: it edits your own line.

**Why (Thierry, 2026-11-12, grilling):** Q7: the whole Outcome; Q14: up to three lines, "but hover doesn't work on mobile, solution?"; Q16: tap to unfold.

**Decision taken here:** a click on the context line already edits your own line. The first tap on a clipped text unfolds it instead of editing, and folding back is a "less" at its end, so the edit stays one tap away.

**Where:** `index.html` `contextOf`, `.ov-ctx` CSS, the `.edit` click handler.

**Claimed by:** Tarek 2026-11-12

**Blocked by:** None

**Status:** done

- [x] Clipped at three lines in the card's width, on the laptop and at phone width -- evidence: `about_pass` at 1700 and 390 px, Chromium, WebKit and Firefox
- [x] A tap on a clipped text unfolds it and does not open the editor; "less" clips it -- evidence: `about_pass`: no `input.inline` after the click, more than three lines, "less" back to three
- [x] A short text still edits on the first click -- evidence: `about_pass`: the editor opens on the first click
