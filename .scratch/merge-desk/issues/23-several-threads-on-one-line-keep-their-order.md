# 23: Several threads on one line keep their order, and only sheaf's threads are marked orphan

**What to fix:** class b/c left by ticket 19 (Nuno's Sonnet round 3, /home/tiroir/Projects/agentview-wt/nuno-19-sonnet-3.md findings 3-4) plus his follow-ups:
- Several threads plus the person's words on one AgentView line come back reordered after a re-hand-over.
- `_orphaned` also edits HTML comments that are not sheaf threads.
- An unclosed `<!--` in a person's line swallows the lines after it (from ticket 16).
- settle does not replace a result line that carries a thread.
- GLOSSARY lacks "record" (.merge-desk.own.json) and "orphan".

**Blocked by:** 19

**Status:** ready-for-agent

- [ ] Two threads and the person's words on one line keep their order across two re-hand-overs (test)
- [ ] A non-sheaf HTML comment is never marked orphan (test)
- [ ] An unclosed `<!--` in a person's line leaves the following items intact (test)
- [ ] GLOSSARY has Record and Orphan
