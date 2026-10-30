# 11: A Paste's copy button does nothing on a phone

**What to fix:** reported by Thierry through Petra (boss, action-list) on 2026-10-30: on the phone, over the tailscale serve address, the copy button of Paste "CI opruimen" (session 9c504ee3, around 23:40Z) did nothing.

Cause, read in `index.html`: the `.pcopy` click awaits `pasteText(id)` (a fetch of `/api/paste_text`) and only then calls `copyText`. Mobile Safari allows a clipboard write only inside the user's gesture; once an `await` has passed, `navigator.clipboard.writeText` and the `execCommand("copy")` fallback both fail. The server side is not it: `/api/paste_text` answers 200 with the text through the tailscale origin (checked 2026-10-30 with a test Paste).

Fix: start the write inside the tap with `navigator.clipboard.write([new ClipboardItem({"text/plain": <promise of the text>})])`, so the fetch finishes behind a write that has already begun; fall back to the old path where `ClipboardItem` is missing or refuses.

**Blocked by:** None.

**Claimed by:** Tarek 2026-10-30

**Status:** ready-for-human

- [x] The clipboard write starts before the fetch resolves -- evidence: Playwright Chromium, iPhone 13 emulation, `fetch` of `/api/paste_text` delayed 600 ms: log `['clipboard.write called', 'fetch resolved']`, clipboard read back `'test copy from Tarek\n'`, button "copied"
- [x] Copy still works on the desktop -- evidence: same check at 1600x1000, same log and clipboard; tests/test_paste.py 85 passed
- [ ] Thierry confirms on his phone (Safari is the browser the cause is about; no WebKit here to run it)
