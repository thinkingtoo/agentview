# 10: Finished sessions

**What to build:** A session idle for `finished_after_minutes` (default 120), with its handover seen and nothing left for the person, becomes a one-line pill at the foot of its column: name and idle time, its working-on line on hover, a click jumps. Pills count toward nothing (card state, summary, header). Any sign of life makes it a tile again. The person can pin a pill open as a tile until unpinned or the session closes; the pin lives in agentview's own state.

**Blocked by:** 09

**Claimed by:** Bettina 2026-10-19 18:56

**Status:** in-progress

- [ ] An unread handover or `n` > 0 keeps a full tile however old
- [ ] A project with only pills shows ALL IDLE
- [ ] A new write turns a pill back into a tile
- [ ] A pin survives polls and ends with the session
