# 18: The copy is checked in Chromium only

**What to build:** `tests/ui_smoke.py` launches only `pw.chromium.launch()` (line 3043 at 5337170). Ticket 15's Firefox and WebKit columns come from a one-off probe that is not in the suite. Nothing guards those engines: a Blob in the `ClipboardItem` drops the leading byte-order mark in all three, and only Chromium would show it again. Decide whether a short copy check should also run in WebKit, the nearest engine to the phone. WebKit here refuses `readText`, so the text has to be read back with a Control+V into a textarea, as the ticket 15 probe did.

**Found in:** Codex review 2 of PR #23 (Opus fallback, run by Runa, 2026-11-11), class c.

**Blocked by:** None.

**Status:** needs-triage

- [ ] Decided: a WebKit copy check, or a written reason why not -- evidence: the check's output, or the reason in this ticket
