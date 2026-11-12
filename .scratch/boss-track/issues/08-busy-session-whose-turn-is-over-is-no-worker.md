# 08: A busy session whose turn is over, with no job, counts as working

**What to build:** `objectives.working` cannot see `turnOver` (it is not kept on the fleet row), so a session whose status says busy for hours after its last reply ended the turn (an API error, a lead with teammates) gets a hammer or an elsewhere entry. Keep `turnOver` on the row and exclude it, unless a subagent is writing (`movement_of`'s rule).

**Found by:** the Opus review of PR 40 (finding 1, low to medium).

**Status:** ready-for-agent

- [ ] A busy session with `turnOver` true, no job, no subagent writing: no hammer, not listed -- evidence: test
