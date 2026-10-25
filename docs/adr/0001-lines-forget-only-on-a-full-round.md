# ADR-0001: Session lines are forgotten only on a round every provider answered

Date: 2026-10-25. Status: accepted.

## Context

The round (`poll.round`) decides what the stores may forget. `marks` keys
its records by `provider:id`, so when one provider misses a
poll the round can still drop the dead sessions of the providers that answered
and keep that provider's records untouched.

Session lines (`lines.py`) are files named by the bare session id, written by
`hooks/team-line` from inside the session, which knows its id and not its
provider. When a provider misses a poll, none of its sessions are live, and no
line file can be told apart from one of its sessions.

## Decision

`lines.forget` runs only when every provider answered the round. `marks.forget`
drops per provider. The round computes both facts in one place.

## Consequences

- A provider that misses polls for a long time holds every stale line file on
  disk for that long. The directory is bounded again on the first full round.
- Aligning `lines` with the per-provider rule needs line files keyed by
  provider, which means changing what every session writes through
  `hooks/team-line` and `hooks/turn_line.py`. That is a separate decision; an
  architecture review should not re-suggest the alignment without it.
