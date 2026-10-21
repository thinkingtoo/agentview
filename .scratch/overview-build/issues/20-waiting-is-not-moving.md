# 20: A session that only waits on a background job is waiting, not moving

**What to build:** a session whose turn has ended and whose only sign of life is an open background job (a watch loop, a long poll, a wait on someone else's action) is shown as waiting on that job, not as moving. Its project card does not turn green for it. The owner asked for this on 2026-10-21, after a project card showed MOVING all evening while every session in it was idle.

**Blocked by:** none

**Claimed by:** Tarek 2026-10-21

**Status:** done

**Merged to origin/dev as** `8ebee41` (with ticket 21), 2026-10-21; seen live: a client project's card WAITING on a 24 h watch job, render-doc workers waiting on their CI watch jobs.

## What happened (Tarek, 2026-10-21, from the live roster)

- A project of five sessions: all five `idle`, none with a call in flight or a subagent writing. One had started a background Bash job: a loop that probes two ports every 5 minutes for up to 24 hours, waiting for a client to open a port forward on their router.
- `fleet.movement_of` counts an open background job as evidence of movement for `WAIT_MAX_MINUTES` (360) minutes, whatever the session's status (`fleet.py`, `evidence = ... or any(t["since"] <= WAIT_MAX_MINUTES for t in jobs)`). So the tile is `moving: True` with the sign "waiting on: <job>, 3 h", the project is `state: "moving"`, and the card is green with MOVING.
- After 6 hours the same job stops counting and the card turns ALL IDLE, while the loop is still running. Neither state says what is true: nothing is working, one thing is waiting on the outside world.

## What it should say

- A session that is `idle` (its turn is over) with open background jobs is **waiting**: its sign stays "waiting on: <job>, <since>", it is not counted as moving, and it does not make its project MOVING.
- The project card shows that it waits (a word and a colour of its own, neither the green of MOVING nor the grey of ALL IDLE), with what it waits on from the job's label, for as long as the job is open: no 6-hour cut-off for this case.
- Unchanged: a `busy` session waiting on a command or a job it started inside its turn is moving, as today, and Hung keeps its rules. Needs you, Error, Hung and Limit still come first on the card.
- The chime does not ring for waiting: nothing is asked of the person.

## Related

- The claude-boss plugin is writing `ci_state(repo, branch)` (its ticket `ci-state/01-ci-state-module.md`): a session waiting on CI is the same kind of state. If the owner wants CI shown in agentview, it should land in this same "waiting" state rather than a second one.

## Boxes

- [ ] An idle session with an open background job is not moving; its sign says what it waits on (test through `roster()` with a fake provider)
- [ ] A project whose only live sign is such a session shows a waiting state on its card, not MOVING and not ALL IDLE, for as long as the job is open
- [ ] A busy session's jobs and commands still count as movement, and Hung is unchanged (the existing tests stay green)
- [ ] Waiting never rings the chime
