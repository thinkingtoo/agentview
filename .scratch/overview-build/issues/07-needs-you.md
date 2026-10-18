# 07: Needs you

**What to build:** A session that waits on the person is marked Needs you: an open question, an open permission prompt, or a session line with `n` > 0, all at one level. The tile shows the reason and its context (the question with its options; the tool and its command; the `ask`, or "3 things left for you"). Commands get a copy button that never answers the session. The project card takes its state from its sessions starting here (NEEDS YOU in amber, MOVING, ALL IDLE), name first and the state word on the second line.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Each of the three sources yields Needs you with the right reason and context
- [ ] The copy button appears on commands only
- [ ] The card's state word sits under the name, never above it
- [ ] Flags for the chime are unchanged
