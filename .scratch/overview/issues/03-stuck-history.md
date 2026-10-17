# What has stuck looked like on this machine so far?

Type: research
Status: resolved
Blocked by: none

## Question

From agentview's own status log and the snapshots, what situations kept a session from moving on over the last weeks? Group them into kinds: a dialog nobody answered, an error loop, a silent hang, waiting on another session, disk full, and anything else the data shows. For each kind: how often (counts), how long it lasted, and which existing flag (stuck, waiting, ready, tool) caught it or missed it. Evidence as dates and counts only.

## Answer

Resolved 2026-10-17. Full findings: `docs/research/stuck-history.md` on the local branch `research/stuck-history` (commit `f563614`, never pushed). Sources: agentview's status log from 2026-09-22 to 2026-10-17 (26 days, 2,630 sessions), crossed with 1,899 transcripts read as record types only, and the system journal. The other 731 sessions have no transcript left. Flags are logged only while a page polls, so "caught" is measurable only with a page open.

| Kind | Count | Duration | Today's flag |
|---|---|---|---|
| Dialog nobody answered | 1,394 waits (1,079 of them AskUserQuestion), 308 over 10 min, 652 h in total | median 4.1 min, max 16 h | `waiting`; missed 14 with a page open |
| Waiting on another session or a background job | 5,601 of 8,262 idle spells (68%); 328 busy silences | median 1.7 to 4.1 min, max 38 h | none names it: idle shows `ready`, busy shows `stuck` |
| Silent hang | 79 at most | median under 10 min | `stuck`, among 481 false ones |
| Rate or usage limit | 28 runs on 4 days | median 3.8 h, max 8.4 h | none; shown as `ready` 14 times, `waiting` 5 times |
| Server or auth errors | 33 runs | max 4.2 h | shown as `ready` |
| Error loops | 8 | under 1.1 min | none; held nobody up |
| Tool running long | 3 | 68 to 90 min | `tool` |
| Disk full | 1 machine-wide (2026-10-17, 2 min) | | no flag can see it |

Permission prompts: 45 of 97 timed out at about 120 s, 44 of them ending with the tool call denied.

False positives: `stuck` 86% (481 of 560): 328 while a subagent or background task worked, 130 the instant a long-idle session went busy again, 23 ended by the session's own tool result. `waiting` 8% (61 of 745 ended within 20 s). `ready` means "your turn" but 68% of idle spells were ended by another session or a job, not the person.
