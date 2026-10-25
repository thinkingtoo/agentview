# 01: The round is one module, `poll.round`, and the handler only serialises

**What to build:** spec `docs/specs/2026-10-25-poll-round.md`, decisions 1, 2, 3, 5, 6, 7, 8. No behaviour change. A new `poll.py` with one entry point `poll.round(providers=None, now=None, seen_path=None, finished_path=None, lines_root=None)` that, under `fleet.POLL` once: asks the providers (`fleet.live`, which returns `(rows, answered, failed)` and takes no lock of its own; `fleet.sessions` keeps returning the rows), builds the roster (`fleet.roster`, which takes the `rows` and `answered` for the banners and keeps `providers=` as a convenience), does today's forgetting exactly as the handler does it (`seen.forget` and `finished.forget` with `answered`, `lines.forget` only when nothing failed), sweeps the Pastes (moved out of `fleet.roster`), merges `providers.broken()` into `failed`, calls `log.note_roster`, and returns the dict the handler serialises with the `providers` status in it. `fleet.ROUND` is deleted; `fleet.banners_of` reads `answered` from its argument. `server.do_GET` for `/api/roster` becomes: call `poll.round()`, add `restore`, `closed`, `saved`, `chime`, send. `tests/test_round.py`'s `Round` class asserts on `poll.round`'s result instead of `fleet.ROUND`.

**Blocked by:** None (can start immediately).

**Claimed by:** Tarek 2026-10-25

**Status:** claimed

- [x] A test of `poll.round` with fake providers and a temp directory, patching nothing but the config path, that fails on 2a96f6b (no `poll` module) and pins: `answered`/`failed` in the result, a failed provider's seen and finished marks surviving the round, lines forgotten only when nothing failed, the sweep having run, the limit banner of a provider that did not answer absent. Evidence: `tests/test_poll.py`, 11 tests; red on the tree without `poll.py` (ModuleNotFoundError), green at b8a158e and after.
- [x] The existing suite green locally on the touched files (415 tests across the route and roster files at 728c2a4) and on t-compute over ssh from `git archive` of the head: b8a158e 2271 OK, 728c2a4 2271 OK, 333ab0e 2272 OK, skipped 4 each.
- [x] Review GO: Matt's `code-review` (standards 4 hard + 6 judgement, spec 3 partial + 5 unasked, all answered in 728c2a4), `/codex-review` round 1 one P2 (lines_root not reaching own_line, fixed in 333ab0e), round 2 clean, GO. Reviews in `/home/tiroir/Projects/agentview-wt/reviews/poll-round-01-codex-{1,2}.md`.
- [ ] Live check on the restarted service (KillMode drop-in checked first): the page loads and polls, `/api/roster` carries `providers`, `events.jsonl` shows no refusal from the page.
