# 15: ui_smoke "copy puts the whole text on the clipboard" fails on dev

**What to build:** find why `paste_pass` in `tests/ui_smoke.py` fails its check "copy puts the whole text on the clipboard, every character and line break", and fix the page or the check, whichever is wrong.

**Found in:** the full smoke run for ticket overview-build/25 (Tarek, 2026-11-11). It failed 3 of 3 runs of `paste_pass` alone on a clean checkout of origin/dev 82f96fb, and the same on the ticket 25 branch. Every other check of the full run passed (452 OK).

**What was seen:** Playwright 1.58.0, Chromium 145.0.7632.6, page at `http://localhost/` with clipboard permissions. The text written is `"﻿Hoi Sven,\n\n\tHe said ...\nGroeten\n"`; what `navigator.clipboard.readText()` returns after the copy click prints as `Hoi Sven, ...` and is not equal. In a bare page in the same browser, `writeText` then `readText` of a string with a leading BOM gives the BOM back, so the browser alone does not drop it. Which character differs was not established.

**Blocked by:** None.

**Status:** needs-triage

- [ ] The check passes, or the page bug it shows is fixed -- evidence: `paste_pass` green three runs in a row
