# 03: A read error that never clears freezes the marks store without a trace

**What to build:** Found in the 2026-10-25 review of `0346f81..04913f8` (Opus fallback, Codex out of tokens). When `marks.json` fails to read with an `OSError` that does not clear (a symlink loop, a path component that is a file, a disk that answers EIO every time), `marks.load` gives `{}` on every round and `mark`, `pin` and `forget` return without writing (`marks.py:114-115`, `marks.py:155-156`). Every idle session then shows ready and unread, the chime rings for all of them, clicks do nothing, and nothing is logged. At 3b8bc91 (ticket 01) the next write replaced the file. The `error` class stays (it stops a short EMFILE from resetting the marks on every poll); the cost to remove is the silence. Needs the file tampered with by hand, so Low.

Decide here, then do: one `log` line when a writer skips on `error` (once per state change, not per poll), or one line why not.

**Decision (Ciro, 2026-10-25):** one `marks_skipped` line in `events.jsonl` (`log.event`) when a writer skips because a read failed, once per state change: `marks._unreadable` holds the stores whose last read failed, and a read that works clears it, so the next failure logs again. Loads log nothing (they run every poll); the writers are where a click goes missing.

**Blocked by:** None (can start immediately)


**Claimed by:** Ciro 2026-10-25 18:55

**Status:** done

- [x] A test that fails on the tree before: a writer that skips on a persistent read error leaves a log line; a recovered read stops logging; no write happens in either case. Evidence: `PersistentReadError` in `tests/test_marks.py`; the new tests run against dev's `marks.py` fail 7 of 10 (the others are guards that pass on both), run 2026-10-25.
- [x] Suite green on the touched files locally and on t-compute; review GO. Evidence: full suite on t-compute at 863792d: 2306 tests OK, 4 skipped, 0 entries left in the private TMPDIR. Matt's code-review answered (Standards: `_stuck` renamed to `_unreadable` since Stuck is a session word, new tests moved above the main guard; Spec: log clears on a finished import, an unsettable broken file logs too). Codex was out of tokens (usage limit, reset 21:39), so two rounds ran as Opus fallback; round 1 found two defects (fixed), round 2 on 863792d: `VERDICT: GO`.

**Restart (2026-10-25 19:17):** merged as b3d1cc3, pushed to dev. `KillMode=process` with `switchover.conf` loaded before and after; the cgroup held only the server; the 23 claude and tmux processes kept their start times; sha256 of `seen.json`, `finished.json`, `marks.json`, `tickets.json` unchanged; tile snapshot identical except one session that went busy → idle between the two snapshots (its own turn ended; stable on a third read).
