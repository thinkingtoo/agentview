# 01: One `marks` store for seen, read and pinned

**What to build:** spec `docs/specs/2026-10-25-marks.md`, decisions 1 to 6. A module `marks.py` with one lock and one file `marks.json`, one record per `provider:id` key (`seen`, `read`, `pinned`), imported once from `seen.json` and `finished.json`, which are left untouched. `seen.py` and `finished.py` go; `fleet`, `poll`, `server` and the tests move to `marks`; `fleet.live` and `poll.round` take `marks_path`.

**Blocked by:** None (can start immediately)


**Claimed by:** Jesper 2026-10-25 13:13

**Status:** done

- [x] Tests that fail on the tree before: a `mark` and a `forget` of another key from two threads both land (today `seen.mark` can lose to `seen.forget`); the import from both old files, from only one, with a bare id, with a corrupt old file, and the old files byte for byte unchanged after; an unreadable `marks.json` loads empty and is not rebuilt. Evidence (2026-10-25): `tests/test_marks.py` 36 tests; on the tree before, the forced click-versus-forget interleaving lost the forget 5 of 5 runs and the module did not import; replacing the lock with a null context fails 4 race tests.
- [x] `fleet.mark_seen` is one `marks.mark(key, stamp, read)` write; `poll.round` reads `marks.keys` and calls `marks.forget` once; `seen.migrate` and its call in `fleet.py` are gone. Evidence: `fleet.mark_seen` is one `marks.mark` call, `poll.round` reads `marks.keys` and calls `marks.forget` once, no `seen.migrate` left.
- [x] `grep -rn "import seen\|import finished\|seen_path\|finished_path" --include=*.py .` finds nothing; `seen.py` and `finished.py` are deleted. Evidence: the grep finds only the one-time import code in `marks.py`, `tests/test_marks.py` and old docs; `seen.py`, `finished.py` and their two test files are deleted.
- [x] The suite green locally on the touched files and on t-compute over ssh; review GO (Matt's code-review, then Codex or Opus). Evidence: touched test files green locally (224 tests in the last run); full suite on t-compute at 3b8bc91: 2287 tests OK, 4 skipped, 0 entries left in the private TMPDIR; Matt's code-review (standards and spec) answered, Codex review of 3b8bc91 `VERDICT: GO`; merged as 3faff7b, production code byte-identical to 3b8bc91.
- [x] The service restarted with the KillMode drop-in checked in place first; the page shows the same ready and unread tiles as before; `marks.json` holds the live keys; `seen.json` and `finished.json` unchanged. Evidence: restart 13:26 with KillMode=process drop-in loaded first; the 22 claude and tmux processes kept their start times; `marks.json` built with 4 records equal to what `seen.json` and `finished.json` hold (4 seen, 4 read, 0 pinned); their sha256 unchanged; roster before and after identical (17 sessions, 16 ready, counts 0/0/1). Pinning on the live data is covered by the tests only, no session was pinned at the time.
