# 34: The relay's flight survives a reset (deskrelay.py, class b)

**What to build:** two ways the single-flight in `deskrelay.py` throws away a good answer or serves a stale one. Found by Codex on ticket 11, head 5ac7bfc, review file /home/tiroir/Projects/agentview-wt/lucas-11-codex-6.md (Sonnet agreed: /home/tiroir/Projects/agentview-wt/lucas-11-sonnet-r1.md findings 1 and 2).

- (`deskrelay.py:184` with `:369`) Followers re-raise a shared 503 (`raise flight.error`), and every request that gets a 503 then calls `HUB.reset()` at line 369. With several requests sharing one failed `sheaf open`: the leader resets first; a new request starts a replacement flight; each old follower then wakes, gets the same 503, and resets again, which invalidates the new flight. Result: several `sheaf open` subprocesses, and fresh followers that run out of `FOLLOW_ROUNDS` and answer "kept going out of date". The test only calls `reset()` once, directly, so the real `serve()` path is not covered. A late or stray 503, including the follower's own "kept going out of date", bumps the generation too (Sonnet finding 1) and can cascade while EventSource reconnects keep arriving.
- (`deskrelay.py:202`) A flight leader returns `flight.value` even when its generation went stale during `make()`. Request A starts locating the hub, request B gets a 503 and resets after the hub moved, then A's old `sheaf open` returns the former port: A goes on against it instead of joining the current-generation flight, which gives a needless 503 or a request to the wrong endpoint. Followers already refuse the stale value (187-188); the leader does not.

A request resets the hub once for the generation it saw: a 503 from a flight older than the current generation does not reset again. A leader whose generation went stale takes the same path as a follower and asks again.

**Blocked by:** none (deskrelay.py only)

**Status:** ready-for-agent

## Acceptance criteria
- [ ] N requests sharing one failed flight cause one reset and no more than one new flight (red test through `serve()` or the same seam the real handler uses, not `reset()` called by hand)
- [ ] A 503 raised for a flight of an older generation does not bump the generation again (red test)
- [ ] A leader whose generation went stale during `make()` does not return the stale value: it joins or starts the current flight (red test, with `make()` blocked on an event while the test resets)
- [ ] The relay's follower cascade does not appear when EventSource-style reconnects arrive while a flight fails (red test, or the line why it needs a real client)
- [ ] Existing single-flight, reset and `FOLLOW_ROUNDS` tests stay green; only the test files this touches are run
- [ ] Red on 5ac7bfc, green after, with the commands and results in the report
