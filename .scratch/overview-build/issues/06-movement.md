# 06: Movement

**What to build:** The person sees that a session is alive. The Claude reader gains per-minute writes over 30 minutes (the session's and its subagents'), whether a shell under it uses CPU, and open background tasks with a live shell. Each tile shows its movement sign ("writing · 8s ago", "waiting on: tests, 12 min", "idle 14 min", replacing the `tool` flag on the page). Each project card shows the 30-minute strip summing its sessions' writes, and "2 moving · 1 stuck · 0 idle".

**Blocked by:** 01

**Claimed by:** Bettina 2026-10-19 00:44

**Status:** in-progress

- [ ] Reader facts tested on fixture transcripts (writes per minute, subagent writes, background tasks)
- [ ] A session with a live background job reads as moving, never idle or stuck
- [ ] The strip has 30 per-minute counts, oldest first, summed across the project's sessions
- [ ] No extra full-file reads: the counters ride on the existing tail reading
