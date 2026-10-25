# The poll round is one module

2026-10-25. From an architecture review (`/improve-codebase-architecture`) and three
rounds of grilling with Thierry; the decisions below are his.

## Why

One poll (`GET /api/roster`) is spread over four places: `server.do_GET` takes
`fleet.POLL`, calls `fleet.roster()`, then reads the module global `fleet.ROUND`
that `fleet.sessions()` wrote as a side effect; the handler does the forgetting
(`seen.forget`, `finished.forget`, `lines.forget`), merges `providers.broken()`
and calls `log.note_roster`; `fleet.roster()` calls `paste.sweep()`, a write
inside a query. The rule "a provider that did not answer must not have its marks
forgotten" is restated in `seen.py`, `finished.py` and `server.py`. Deleting the
forget calls from the handler breaks nothing at compile time, only silently.
Tests reach the round by patching nine module globals.

## Vocabulary

**Round** (in `GLOSSARY.md`): one poll, ask every provider, build the roster,
settle what is forgotten, sweep the Pastes. Module `poll.py`, entry point
`poll.round(...)`. The file is not `round.py`, which would shadow the builtin.

## Decisions

1. **Seam.** A new module `poll.py`; `fleet.roster()` stays a query and the
   round calls it. `fleet.py` takes on no new job (it grew by the parameters
   below, 13 lines).
2. **No global.** `fleet.live()` returns `(rows, answered, failed)`
   (`fleet.sessions()` keeps returning the rows alone, for `members` and the
   tests that call it); `fleet.ROUND` is gone. `fleet.roster()` takes the
   `rows` and `answered`, and `members` takes `rows`, so the round asks the
   providers once; `banners_of` takes `answered` (a provider's limit banner
   shows only when it answered; None means everyone did). The handler
   receives one dict from `poll.round` and serialises it.
3. **The sweep leaves the query.** `paste.sweep()` moves from `fleet.roster()`
   to the round, after the roster is built.
4. **One forget decision, two facts.** The round computes once: the set of
   `provider:id` keys a keyed store may drop (gone sessions of providers that
   answered), and a boolean "every provider answered". `seen.forget` and
   `finished.forget` lose their `answered` parameter and drop only the keys
   they are given. `lines.forget` runs only when every provider answered,
   because line files are keyed by bare session id and cannot be told apart
   by provider (ADR-0001). Re-keying line files is out of scope.
5. **What else moves into the round.** `providers.broken()` merged into
   `failed`, `log.note_roster(flags)`, the `providers` status dict. What stays
   in the handler: `restorable`, `closed_now`, `coverage` (Claude-only, a
   provider-seam question for later) and the `chime` setting.
6. **Dependencies are accepted, not created.**
   `poll.round(providers=None, now=None, seen_path=None, finished_path=None,
   lines_root=None)`, defaults resolving to the existing `store()` functions.
   A test passes a temp directory and fake providers and patches nothing
   but the config path (`fleet.CONFIG`, a module global until there is a
   config module). The Paste store is beside the lines store
   (`paste.store(lines_root)`), so it needs no parameter of its own.
   `providers.broken()` and `log.note_roster` stay module calls.
7. **Lock.** The whole round, forget and sweep included, runs under one lock.
   The lock object stays in `fleet` as `fleet.POLL` because `fleet.find` and
   `fleet.look` (the click path) serialise provider access with the same lock
   and `poll` imports `fleet`; the round takes it once around everything, and
   `fleet.sessions` no longer takes it itself.
8. **The test seam survives.** `fleet.roster(providers=...)` keeps accepting
   providers as a convenience that runs the ask inside, so the ~100 test call
   sites keep working. `tests/test_round.py`'s `Round` class moves to
   `poll.round`.
9. **Two tickets.** `01` moves the mechanics with no behaviour change (1, 2, 3,
   5, 6, 7, 8). `02`, blocked by 01, reshapes forget (4).
10. **Gate per ticket.** A test that fails on the tree before the change,
    Matt's `code-review` then `/codex-review` (Opus at once if Codex is out),
    the suite on t-compute over ssh (`git archive` of the head, private TMPDIR,
    `python3 -m unittest discover -s tests`; this repo has no CI), and for 01 a
    live check on the restarted service, the restart done only with the
    KillMode drop-in in place.

## Out of scope

Candidates 2 to 8 of the review (fleet.py split, what rings, project identity,
request admission, Paste card ownership, the two stores, provider identity).
Candidate 7 (seen/finished as one keyed store) becomes cheap after 02 and is
noted in `NEXT.md` when 02 is done.
