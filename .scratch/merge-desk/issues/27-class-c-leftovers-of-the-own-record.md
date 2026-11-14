# 27: Class c leftovers of the own record

**What to fix:** class c findings of the Sonnet review of ticket 19 (/home/tiroir/Projects/agentview-wt/nuno-19-sonnet-5.md), each needing a test first:
- a page with CRLF line ends: none of our lines match the record, so the old block stays and an LF block is appended;
- `settle` on an item with no record does not record the result line, so refused presses pile up `Not merged:` lines;
- a page two generations behind its record (a hand-over lost between) duplicates lines;
- with no record the task title never updates on a hand-over;
- an unterminated comment on one of our lines makes that line the person's, so a second `Recommendation:` is appended.
- `desk adopt` (ticket 19, Sonnet round 7): a person's 4-space line right after the real ships bullets is adopted as ours (the same ambiguity as ticket 26);
- `desk adopt` checks the record file before it takes the lock, so a record changed between the check and the edit is not rechecked;
- `desk adopt` with case-duplicate keys (`A/b#1` and `a/b#1`) reports only the first as adopted.

**Blocked by:** 19

**Status:** ready-for-agent

- [ ] CRLF page: a hand-over replaces our lines, no LF block appended (test)
- [ ] settle with no record: a second refused press replaces the first result line (test)
- [ ] A page two generations behind its record does not duplicate lines (test)
- [ ] No record: a hand-over still updates the task title, or the item says why not (test)
- [ ] An unterminated comment on our line does not add a second Recommendation (test)
- [ ] adopt: a person's 4-space line after the ships bullets is not adopted, or the item is skipped (test)
- [ ] adopt: the record check happens under the lock (test)
- [ ] adopt: case-duplicate keys are all reported (test)
