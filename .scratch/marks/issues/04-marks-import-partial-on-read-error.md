# 04: A short read error during the one-time import makes the import permanently partial

**What to build:** Found in the 2026-10-25 review of `0346f81..04913f8` (Opus fallback, Codex out of tokens). The importer reads `seen.json` and `finished.json` through `_json`, which swallows every `OSError` as "no file" (`marks.py:64-69`, used at `:86` and `:90`). With no `marks.json`, a short EMFILE or EIO on the first start writes a `marks.json` without the seen stops, and the import never runs again: every session is ready for good. The same happens when the reread under the lock in `load` (`marks.py:128-131`) returns `error` just before a write. Moot in production (the import ran at the 2026-10-25 13:26 restart, 4 records equal to the old files); it comes back only if `marks.json` is deleted. Not the accepted `RecursionError` case. Low.

Decide here, then do: when an old file fails with an `OSError` other than "not found", do not write `marks.json` that round (load gives `{}`, the import retries next round), or one line why not.

**Decision (Ciro, 2026-10-25):** do as the ticket says. `_json` tells "not there / not JSON" (adds nothing) from a failed read; `_imported` returns None for the latter and `_build` (new, under the lock) then writes no `marks.json`. `load` gives `{}` and retries next round. A writer that finds the file missing goes through the same `_build`, so it cannot start the file without the old records either (this covers the reread under the lock). Such a skip is also logged (ticket 03).

**Blocked by:** None (can start immediately)


**Claimed by:** Ciro 2026-10-25 18:55

**Status:** done

- [x] A test that fails on the tree before: a read error on `seen.json` or `finished.json` with no `marks.json` writes nothing and the next load, once the read works, imports every record; a missing old file still counts as empty. Evidence: `ImportReadError` in `tests/test_marks.py`, failing on dev before the fix. An old file that is unreadable by permission or is a directory still adds nothing (as `_read` treats it), a regression the round-1 review caught, covered by a test. Known gap: no chmod 000 test (the directory case covers the same branch; chmod is a no-op as root).
- [x] Suite green on the touched files locally and on t-compute; review GO. Evidence: full suite on t-compute at 863792d: 2306 tests OK, 4 skipped, 0 entries left in the private TMPDIR. Matt's code-review answered (Standards: `_stuck` renamed to `_unreadable` since Stuck is a session word, new tests moved above the main guard; Spec: log clears on a finished import, an unsettable broken file logs too). Codex was out of tokens (usage limit, reset 21:39), so two rounds ran as Opus fallback; round 1 found two defects (fixed), round 2 on 863792d: `VERDICT: GO`.
