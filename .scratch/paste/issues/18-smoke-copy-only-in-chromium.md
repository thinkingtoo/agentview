# 18: The copy is checked in Chromium only

**What to build:** `tests/ui_smoke.py` launches only `pw.chromium.launch()` (line 3043 at 5337170). Ticket 15's Firefox and WebKit columns come from a one-off probe that is not in the suite. Nothing guards those engines: a Blob in the `ClipboardItem` drops the leading byte-order mark in all three, and only Chromium would show it again. Decide whether a short copy check should also run in WebKit, the nearest engine to the phone. WebKit here refuses `readText`, so the text has to be read back with a Control+V into a textarea, as the ticket 15 probe did.

**Found in:** Codex review 2 of PR #23 (Opus fallback, run by Runa, 2026-11-11), class c.

**Blocked by:** None.

**Status:** done

**Claimed by:** Samir 2026-11-11

- [x] Decided: a WebKit copy check, or a written reason why not -- evidence: the check's output, or the reason in this ticket

## Evidence

**Samir, 2026-11-11.** Decided: a short copy check in WebKit and Firefox both, because both engines are already installed here (Playwright 1.58 under python3.12; `playwright install --dry-run` lists chromium-1208, firefox-1509 and webkit-2248, each with `INSTALLATION_COMPLETE`). Adding them cost about 30 seconds of the run and no install. The default `python3` has no Playwright; the smoke runs under python3.12, as before.

New `paste_engine_pass` in `tests/ui_smoke.py`, run by `main` in WebKit then Firefox after the Chromium passes. Neither engine takes the clipboard permissions, so the page is opened without them: the copy click is the gesture, and the text is read back by a Control+V into a textarea appended to the page. Three checks per engine: the button says copied, the text is the Paste's whole text with its leading byte-order mark, and `/api/paste_copied` was told.

Green:

```
webkit: the button says it copied                          OK
webkit: copy puts the whole text on the clipboard, byte-order mark included OK
webkit: and told the server                                OK
firefox: the button says it copied                         OK
firefox: copy puts the whole text on the clipboard, byte-order mark included OK
firefox: and told the server                               OK
```

Red, with the item's promise giving a Blob again (`return t;` -> `return new Blob([t], { type: "text/plain" });`, the ticket 15 bug):

```
webkit: copy puts the whole text on the clipboard, byte-order mark included FAILED 'Hoi Sven,\n\n\tHe said ...
firefox: copy puts the whole text on the clipboard, byte-order mark included FAILED 'Hoi Sven,\n\n\tHe said ...
```

What it does not catch: `await textPromise;` before the `write` (the paste/11 bug) stays green in both desktop engines. Their gesture window outlasts a routed fetch, so the late write is still allowed. Chromium's check "started before the text came back" and ticket 17's "inside the tap, before any await" cover that order. The phone itself is still ticket 16.
