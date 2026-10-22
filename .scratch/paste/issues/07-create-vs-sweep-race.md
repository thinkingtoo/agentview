# 07: A slow `create` can lose its text to `sweep`

**What to build:** finding 1 of `/home/tiroir/Projects/agentview-wt/reviews/paste-codex-followup-2.md` (Codex, head 99d586f, VERIFIED). `create` writes `<id>.txt` and then `<id>.json` outside `_changing` (paste.py:130-140); `sweep` removes a text older than `SWEEP_AFTER` that has no record (paste.py:274-290). A creator stalled past that age between the two writes has its text swept, then writes the record and reports success for a Paste without text. Close the window (hold the lock across both writes, or make sweep respect it) and test it with a stalled creator.

**Blocked by:** None (can start immediately).

**Claimed by:** none

**Status:** ready-for-agent

- [ ] A test with a creator stalled between the writes beyond the sweep age: fails on 99d586f, passes after the fix
- [ ] Review GO on the fix, suite on t-compute green
