# 02: The round decides once what is forgotten; the stores only drop what they are told

**What to build:** spec `docs/specs/2026-10-25-poll-round.md`, decision 4, and ADR-0001. `poll.round` computes two facts: `droppable`, the set of `provider:id` keys that are not live and whose provider answered; and `full`, whether every provider answered. `seen.forget(droppable, path)` and `finished.forget(droppable, path)` lose their `answered` parameter and drop exactly the keys given (a key not in the store is nothing). `lines.forget` is called only when `full`. The `Forgetting` tests in `tests/test_round.py` move to the round's level: a failed provider's marks survive because the round never names them, not because the store filters them.

**Blocked by:** 01

**Claimed by:** Tarek, 2026-10-25

**Status:** in progress

- [ ] A test at the round's level that fails before the change: with providers A (answered) and B (failed), B's seen mark, finished read and pin survive, A's gone session loses all three, and no line file is removed; with both answered, the line file of a gone session is removed.
- [ ] `seen.forget` and `finished.forget` take only the keys to drop; `grep -n answered seen.py finished.py` finds nothing.
- [ ] The suite green locally on the touched files and on t-compute over ssh; review GO (code-review, then Codex or Opus).
- [ ] `NEXT.md` notes candidate 7 of the review (one keyed store under seen and finished) as now cheap.
