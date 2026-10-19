# 03: Correcting projects by hand

**What to build:** The person can move a session, a whole track or a whole repository into a project, rename a project and merge two, from the page. Each project card has a pin button: pinned projects lead in the order they were pinned, with left/right arrows on pinned cards to reorder and the pin again to unpin (owner, 2026-10-19). A move for a track or repository holds for future sessions; a single-session move lasts as long as that session. Stored in `config.json` (`assign` keyed by track or repository as well as by session, `names`).

**Blocked by:** 02

**Claimed by:** Joaquin 2026-10-19 09:47

**Status:** in-progress

- [x] Moving a repository into a project places a new session from that repository there
- [x] A single-session move ends with that session
- [x] Rename and merge survive a restart of the server
- [x] Pinning, reordering and unpinning a project from its card is stored in `pinned` and orders the columns (roster test plus smoke run)
- [x] Covered through `roster()` with a test config

## Evidence (Joaquin, 2026-10-19; branch `overview/03-by-hand`, gate head `702624b`)

Mistral round 3 `VERDICT: GO` on 702624b (`reviews/mistral-review-03-3.md`; rounds 1 and 2 NO-GO, no real bug among 18 findings, replies with evidence in `replies-03-1.md` and `replies-03-2.md`). Code-review (Standards and Spec) done before it; real findings fixed. Unit suite 962 tests OK (skipped=1); page smoke `tests/ui_smoke.py` 227 checks green on a port-0 test server; the owner's `config.json` sha256 769cd744b9dbcb57e3e749af216faa2156b52185115194b43fec4409d35fc802 before and after. History check clean (7 commits, 0 non-noreply identities). Not merged: waits for the boss's order.

- Box 1: `tests/test_by_hand.py` `Moves.test_moving_a_repository_into_a_project_places_a_new_session_from_it_there` (a session that starts later, in a second clone of the remote, lands in the track), `test_moving_a_track_takes_every_session_of_the_track_with_it`.
- Box 2: `Moves.test_a_single_session_move_ends_with_that_session` (the next session started where it started is not carried along, no column left behind). Entries for ended sessions are not deleted from `config.json` on purpose: a closed conversation reopens with the same key (`server._reopen`, `claude:<sid>`), and its move should still hold.
- Box 3: `Pins.test_a_pin_survives_a_restart_of_the_server`, `Renames.test_a_rename_is_the_name_on_the_column_and_survives_a_restart`, `Merges.test_merging_puts_every_session_of_the_project_into_the_other_and_survives_a_restart` (a second server on the same config file); smoke `e2e_pass`: after killing and restarting the test server the pins, name and merge are all still there and the config is not rewritten.
- Box 4: `Pins` (pin order, arrow swap, a pin over a project with no column, unpin, plain-name pins, malformed requests refused); smoke `hand_pass` (what the page asks and shows) and `e2e_pass` (pin, arrow, unpin read back from `config.json`).
- Box 5: all of it through `fleet.roster()` or `/api/roster` with a config in a temp dir; the real config is never written.
- Premortem risks: R1 and R13 `OldConfig` (an old config places its sessions as before; the migration prefixes a bare key and leaves `track:`, `repo:` keys alone; idempotent; a `provider:id` is never read as a project). R2 `Concurrency` (rename, move, pin, line, hold and merge sent at once through the real routes with `json.dump` slowed: all land; no temp file left; fails without the lock, checked by mutation). R10 `Renames.test_renaming_keeps_...` and `Merges` (pin, line and moves that pointed at the absorbed project move with it; nothing left pointing at it; legacy plain-name pins and renames handled).
- Mutation checks on a copy of the tree: 12 of 12 mutants killed.
- Beyond the boxes, found and fixed on the way: a merge can be undone from the card (a project moved into nothing), the block view's `/api/order` no longer erases overview pins, arrows ignore cards a filter hides, the tile says `assigned` so the way back shows on the real page.
- Known, not mine: the block view's ordering (`fleet.order_blocks`) crashes the roster when `pinned` holds an unhashable entry (a dict or list written by hand), on origin/dev as well.
