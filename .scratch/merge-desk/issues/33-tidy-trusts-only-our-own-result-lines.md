# 33: `tidy` trusts only our own result lines (deskscan.py, class a)

**What to build:** `over()` in `deskscan.py` judges an item's story over from `results(it.block)`, every result-shaped line in the block, without asking the ownership record. Found by Codex on ticket 19, head 5059517, review file /home/tiroir/Projects/agentview-wt/nuno-19-codex-6.md (Codex cited `deskscan.py:449`; the logic is `over()`, lines 431-445, `said = results(it.block)` at 439 and the `any(l.startswith(("  - Merged", ...)) for l in said)` test at 441).

Failing scenario: an item has an old `merged` event in the history log (a day or more ago). The person writes their own line `  - Merged at 12:00` in the item. AgentView's real result line was removed or changed. `over()` takes the person's line for ours, so `tidy()` judges the story complete and deletes the whole item, with the person's notes in it. The same shape holds for the `Installed` and `Already installed` lines of the `installed` branch (443-445) and for `NOT_WELL`.

`over()` reads the record of the item (`deskfile` `_own`) and counts a result-shaped line only when the record says the line is ours. An item with no record is never tidied by its result lines.

**Blocked by:** none (deskscan.py only; may run beside 31, 32 and 34. If it needs a `deskfile` function from 31, take it as it is on dev.)

**Status:** ready-for-agent

## Acceptance criteria
- [ ] A person's `  - Merged at 12:00` line, with an old `merged` event and no result line of ours in the record, does not make `over()` true, and `tidy()` keeps the item and its notes (red test)
- [ ] The same for the `installed` branch: a person's `  - Installed` line does not make the story over (red test)
- [ ] An item whose result line is ours (the record says so), a day after the event, is still tidied (existing tests stay green)
- [ ] An item with no ownership record is not tidied on the strength of its result lines (red test)
- [ ] `tidy()` still judges again under the desk lock on the text the drop is made on (existing test stays green)
- [ ] Red on 5059517, green after, with the commands and results in the report
