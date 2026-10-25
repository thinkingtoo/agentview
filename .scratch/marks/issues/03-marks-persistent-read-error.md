# 03: A read error that never clears freezes the marks store without a trace

**What to build:** Found in the 2026-10-25 review of `0346f81..04913f8` (Opus fallback, Codex out of tokens). When `marks.json` fails to read with an `OSError` that does not clear (a symlink loop, a path component that is a file, a disk that answers EIO every time), `marks.load` gives `{}` on every round and `mark`, `pin` and `forget` return without writing (`marks.py:114-115`, `marks.py:155-156`). Every idle session then shows ready and unread, the chime rings for all of them, clicks do nothing, and nothing is logged. At 3b8bc91 (ticket 01) the next write replaced the file. The `error` class stays (it stops a short EMFILE from resetting the marks on every poll); the cost to remove is the silence. Needs the file tampered with by hand, so Low.

Decide here, then do: one `log` line when a writer skips on `error` (once per state change, not per poll), or one line why not.

**Blocked by:** None (can start immediately)


**Claimed by:** Ciro 2026-10-25 18:55

**Status:** in-progress

- [ ] A test that fails on the tree before: a writer that skips on a persistent read error leaves a log line; a recovered read stops logging; no write happens in either case.
- [ ] Suite green on the touched files locally and on t-compute; review GO.
