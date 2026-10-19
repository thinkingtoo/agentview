# 08: Limit, Error and Hung

**What to build:** The remaining stuck kinds. Limit: a rate-limit API error is the last record, with the reset time when given and how long it has been held. Error: any other API or auth error as the last record, with its type. Hung: busy, but not moving (by the movement rule) for `hung_after_minutes` (default 10), with the last tool and its age. The card's state follows the full order: Needs you, Error, Hung, Limit, moving, idle. Waiting on jobs and idle are never stuck. Today's `stuck` stays computed for the chime.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Each kind is detected from fixture records and shown with its reason and context
- [ ] A session waiting on a subagent or background job is never Hung
- [ ] The card colour follows the full precedence
- [ ] `hung_after_minutes` is read from config
- [ ] The card's mix line counts stuck by kind, the same way the card state does: a session counted stuck always has a stuck kind on its tile, and a menu or dialog the person opened is not stuck (raised in 07, 2026-10-19)
