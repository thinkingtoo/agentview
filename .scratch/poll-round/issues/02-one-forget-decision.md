# 02: The round decides once what is forgotten; the stores only drop what they are told

**What to build:** spec `docs/specs/2026-10-25-poll-round.md`, decision 4, and ADR-0001. `poll.round` computes two facts: `droppable`, the set of `provider:id` keys that are not live and whose provider answered; and `full`, whether every provider answered. `seen.forget(droppable, path)` and `finished.forget(droppable, path)` lose their `answered` parameter and drop exactly the keys given (a key not in the store is nothing). `lines.forget` is called only when `full`. The `Forgetting` tests in `tests/test_round.py` move to the round's level: a failed provider's marks survive because the round never names them, not because the store filters them.

**Blocked by:** 01

**Claimed by:** Tarek, 2026-10-25

**Status:** done

- [x] A test at the round's level that fails before the change: with providers A (answered) and B (failed), B's seen mark, finished read and pin survive, A's gone session loses all three, and no line file is removed; with both answered, the line file of a gone session is removed. Done in `tests/test_poll.py` `Forgetting`; the round's behaviour for providers that fail a poll was already this, so those tests passed before. The one that fails on the tree before is `test_lines_are_kept_while_a_provider_is_broken_since_start_up` (a provider whose module did not load made the round count as full; the spec review found it). The store tests that fail before: `test_seen.py` and `test_finished_state.py`, 4 failures.
- [x] `seen.forget` and `finished.forget` take only the keys to drop; `grep -n answered seen.py finished.py` finds nothing.
- [x] The suite green locally on the touched files and on t-compute over ssh; review GO (code-review, then Codex or Opus). Touched files 126 OK locally; t-compute c0a4e0d 2271 OK, 5afd5ab 2272 OK, skipped 4 each. Standards and spec review applied in 5afd5ab; Codex GO with no findings.
- [x] `NEXT.md` notes candidate 7 of the review (one keyed store under seen and finished) as now cheap.
