# 19: A hand-over tells the person's lines from AgentView's

**What to fix:** ticket 16's `deskfile.carry` replaces AgentView's own lines by shape, so three cases still lose or move the person's text (Alonso, 16's limits, class c): a person's own 4-space note directly under `What ships:` reads as a ships bullet and is replaced; a person line that exactly matches one of AgentView's line shapes is replaced; a thread whose line is gone moves to the end of the item and its quote anchor may no longer match. Mark AgentView's lines unambiguously (or keep a record of what AgentView wrote last) so nothing the person wrote is ever taken for ours.

**Blocked by:** 16

**Claimed by:** Maja 2026-11-14 02:59

**Status:** in-progress

- [ ] A person's 4-space note under What ships survives a re-hand-over (test)
- [ ] A person line shaped like "  - Recommendation: ..." survives (test)
- [ ] A thread whose line is replaced keeps an anchor sheaf still finds (test against sheaf's anchor rule)
