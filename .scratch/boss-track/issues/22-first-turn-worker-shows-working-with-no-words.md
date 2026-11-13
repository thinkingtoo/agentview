# 22: A worker on its first turn shows "working" and nothing else

**What happened:** Elif on chat-box showed "working", the last fallback of `_own_words`. Kian (this ticket's author) shows the same on agentview at this moment.

**Cause:** `_own_words` reads three fields: the team-line `did`, the card `title` and the `prompt`. Early in a session none is set. The `prompt` field comes from the `last-prompt` record, which a typed prompt writes. Kian's row, checked at that moment: status busy, `lineSource: place`, line "dev", and none of the three. Elif's later row carries a `did` and prints it, so the fallback only holds early in a session.

**Decision (Tarek, 2026-11-13):** with no did, no title and no last prompt, show the first line of the newest dispatch the session received (the cross-session message in its transcript) before "working". First check that the transcript holds that message and in which record shape; build only on what is observed. Built in one PR with 21, after PR 48 merges.

**Status:** ready-for-agent, after the record shape is checked

- [ ] The record shape of a received cross-session message is written here, from a real transcript -- evidence: a quoted record with identifiers redacted
- [ ] A session with no did, title or prompt shows the first line of its newest dispatch; with any of the three it does not -- evidence: a test in `tests/test_objectives.py`
- [ ] The transcript is read only for the tail the row already reads, never whole -- evidence: the reader's existing budget
