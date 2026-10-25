# 01: One `marks` store for seen, read and pinned

**What to build:** spec `docs/specs/2026-10-25-marks.md`, decisions 1 to 6. A module `marks.py` with one lock and one file `marks.json`, one record per `provider:id` key (`seen`, `read`, `pinned`), imported once from `seen.json` and `finished.json`, which are left untouched. `seen.py` and `finished.py` go; `fleet`, `poll`, `server` and the tests move to `marks`; `fleet.live` and `poll.round` take `marks_path`.

**Blocked by:** None (can start immediately)

**Claimed by:** Youssef 2026-10-25 12:54

**Status:** in-progress

- [ ] Tests that fail on the tree before: a `mark` and a `forget` of another key from two threads both land (today `seen.mark` can lose to `seen.forget`); the import from both old files, from only one, with a bare id, with a corrupt old file, and the old files byte for byte unchanged after; an unreadable `marks.json` loads empty and is not rebuilt.
- [ ] `fleet.mark_seen` is one `marks.mark(key, stamp, read)` write; `poll.round` reads `marks.keys` and calls `marks.forget` once; `seen.migrate` and its call in `fleet.py` are gone.
- [ ] `grep -rn "import seen\|import finished\|seen_path\|finished_path" --include=*.py .` finds nothing; `seen.py` and `finished.py` are deleted.
- [ ] The suite green locally on the touched files and on t-compute over ssh; review GO (Matt's code-review, then Codex or Opus).
- [ ] The service restarted with the KillMode drop-in checked in place first; the page shows the same ready and unread tiles as before; `marks.json` holds the live keys; `seen.json` and `finished.json` unchanged.
