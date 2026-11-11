# 15: ui_smoke "copy puts the whole text on the clipboard" fails on dev

**What to build:** find why `paste_pass` in `tests/ui_smoke.py` fails its check "copy puts the whole text on the clipboard, every character and line break", and fix the page or the check, whichever is wrong.

**Found in:** the full smoke run for ticket overview-build/25 (Tarek, 2026-11-11). It failed 3 of 3 runs of `paste_pass` alone on a clean checkout of origin/dev 82f96fb, and the same on the ticket 25 branch. Every other check of the full run passed (452 OK).

**What was seen:** Playwright 1.58.0, Chromium 145.0.7632.6, page at `http://localhost/` with clipboard permissions. The text written is `"﻿Hoi Sven,\n\n\tHe said ...\nGroeten\n"`; what `navigator.clipboard.readText()` returns after the copy click prints as `Hoi Sven, ...` and is not equal. In a bare page in the same browser, `writeText` then `readText` of a string with a leading BOM gives the BOM back, so the browser alone does not drop it. Which character differs was not established.

**Blocked by:** None.

**Claimed by:** Runa 2026-11-11

**Status:** done

**Cause:** the page, not the check. Ticket paste/11 made `copyFetched` hand the `ClipboardItem` a promise of a `Blob`. Browsers decode a `text/plain` Blob as UTF-8 and drop a leading byte-order mark, so a Paste that starts with U+FEFF reached the clipboard one character short. Every other character, the tab and the line breaks included, arrived intact (30 of 31). Fix: the promise gives the string itself, which `ClipboardItem` accepts.

- [x] The check passes, or the page bug it shows is fixed -- evidence: `paste_pass` green three runs in a row

## Comments

**Runa, 2026-11-11.** Which character: probed in a bare routed page, the same text written four ways and read back.

| Way | Chromium 145 | Firefox (Playwright 1.58) | WebKit 26.0 (Linux desktop build) |
|---|---|---|---|
| `writeText(t)` | kept | kept | kept |
| `ClipboardItem` with a `Blob` (also a promise of one) | U+FEFF dropped, 30/31 | U+FEFF dropped, 30/31 | U+FEFF dropped, 30/31 |
| `ClipboardItem` with a promise of the string | kept | kept | kept |

WebKit refuses the clipboard outside a gesture, so there both writes ran from a click, the string promise resolved 300 ms after the click (as the fetch does, the paste/11 case), and the clipboard was read back by a Control+V into a textarea. It accepted the late string promise. This is the desktop WebKit build, not iOS Safari: Thierry's phone has not seen this change.

A new check pins the way the text went: `clipboard.write` and `writeText` are wrapped, and the copy must have called `write` only. Without it the check stays green when the `ClipboardItem` write throws and the `writeText` fallback copies the same text (it happened once here, while fixing).

Mutations of `index.html`, each with `paste_pass` alone, `PYTHONDONTWRITEBYTECODE=1`, the landing proven by `diff`, restored and its hash checked:

| Mutation | Result |
|---|---|
| `return t;` back to `return new Blob([t], { type: "text/plain" });` | FAILED "copy puts the whole text on the clipboard, every character and line break" |
| `"text/plain": promised` -> `"text/plain": nope` (the write throws, the fallback copies) | FAILED "and it went through the ClipboardItem started in the tap, not a fallback" |
| `if (window.ClipboardItem` -> `if (false && window.ClipboardItem` | FAILED the same check |

Evidence: `paste_pass` and `paste_stay_pass` together, three runs in a row, each 40 OK, no failure, no page or console error, exit 0. Routed passes only, so no server was started. Laptop load 13 to 18 on 16 cores during the runs.
