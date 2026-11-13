# 11: Relay follow-ups: the lock across sheaf calls, a cap on streams, who may edit comments

**What to build:** three small hardenings of the desk relay (`deskrelay.py`), found in the Opus reviews of ticket 07 (class c, none blocks use by Thierry's own devices). Reviews: /home/tiroir/Projects/agentview-wt/sigrid-07-reviews.md.

**Blocked by:** 07

**Status:** needs-triage

- [ ] The relay's lock is not held across `sheaf open` (up to 60 s) and the sign-in (up to 45 s): after a 503 reset, desk requests from several devices must not queue behind one subprocess
- [ ] One device cannot hold unlimited `/_/live` streams: each holds an AgentView thread and a hub connection with no cap per client today
- [ ] The comment route lets whoever reaches :8445 edit, delete and resolve the owner's own comments on the desk (all five `op` values pass); decide whether the relay passes only `add` and `reply`, and test it
