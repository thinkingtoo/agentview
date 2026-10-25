# 02: Marks cleanups from the ticket 01 review, and no silent overwrite of an unreadable `marks.json`

**What to build:** (1) A `mark`, `pin` or `forget` on a `marks.json` that exists but cannot be read must not overwrite it silently: move it aside first (`marks.json.broken-<timestamp>`), then write. Spec decision 3 stays: it loads as empty and is never rebuilt from the old files; writes never raise. The `marks.py` docstring that says the next write goes over it is updated. (2) The standards-review calls from ticket 01, each decided here (do it, or one line why not): `remembered` in `fleet.py` becomes `state`; the two duplicate read blocks in `marks.load` become one; the `keys()` thin wrapper; the unused return values of `mark` and `pin`. Behaviour unchanged; no change beyond these.

**Blocked by:** None (can start immediately)

**Claimed by:** Ciro 2026-10-25 18:25

**Status:** in-progress

- [ ] A test that fails on the tree before: an unreadable `marks.json` is moved aside to `marks.json.broken-<timestamp>` with its bytes intact by a mark, a pin and a forget, and the write lands in a fresh file; it still loads as empty, is not rebuilt from the old files, and a write never raises (an unmovable file included).
- [ ] The four review calls decided and said here: `remembered` → `state` in `fleet.py`; one read block in `marks.load`; `keys()`; return values of `mark`/`pin`.
- [ ] Suite green locally on the touched files and on t-compute over ssh; review GO (Matt's code-review, then Codex or Opus).
- [ ] The service restarted with the KillMode drop-in checked first; same process start times, `marks.json` records unchanged, same tiles.
