# 04: A short read error during the one-time import makes the import permanently partial

**What to build:** Found in the 2026-10-25 review of `0346f81..04913f8` (Opus fallback, Codex out of tokens). The importer reads `seen.json` and `finished.json` through `_json`, which swallows every `OSError` as "no file" (`marks.py:64-69`, used at `:86` and `:90`). With no `marks.json`, a short EMFILE or EIO on the first start writes a `marks.json` without the seen stops, and the import never runs again: every session is ready for good. The same happens when the reread under the lock in `load` (`marks.py:128-131`) returns `error` just before a write. Moot in production (the import ran at the 2026-10-25 13:26 restart, 4 records equal to the old files); it comes back only if `marks.json` is deleted. Not the accepted `RecursionError` case. Low.

Decide here, then do: when an old file fails with an `OSError` other than "not found", do not write `marks.json` that round (load gives `{}`, the import retries next round), or one line why not.

**Blocked by:** None (can start immediately)


**Claimed by:** Ciro 2026-10-25 18:55

**Status:** in-progress

- [ ] A test that fails on the tree before: a read error on `seen.json` or `finished.json` with no `marks.json` writes nothing and the next load, once the read works, imports every record; a missing old file still counts as empty.
- [ ] Suite green on the touched files locally and on t-compute; review GO.
