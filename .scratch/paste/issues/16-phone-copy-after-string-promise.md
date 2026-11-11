# 16: Check a Paste's copy on the phone after the ClipboardItem change of ticket 15

**What to check:** ticket 15 changed what `copyFetched` hands the `ClipboardItem`: a promise of the string instead of a promise of a `Blob`. Chromium, Firefox and the Linux desktop WebKit build accept it and copy the whole text, but iOS Safari, the browser ticket 11 is about, has not been tried. If it refused the string, the copy would fall back to `writeText` after the fetch, outside the tap, and the button would do nothing on the phone again.

**Found in:** the Spec review of ticket 15 (Runa, 2026-11-11).

**Blocked by:** PR #23 merged and the page reloaded on the phone.

**Status:** ready-for-human

- [ ] Thierry copies a test Paste from Safari on his phone, over the tailscale serve address, and the text arrives whole -- evidence: his word, with the Paste's title and the time
