# Which kinds of stuck does the overview name, and how is each detected?

Type: grilling
Status: resolved
Blocked by: 02, 03

## Question

Using "What signals show that a session is moving?" and "What has stuck looked like on this machine so far?": which kinds of stuck get their own name on the overview? For each, the detection rule, the reason shown to the person, the context shown with it, and how it relates to today's flags (stuck, waiting, ready, tool). Which situations are left to the movement sign alone?

## Answer

Resolved 2026-10-18 by grilling, in two rounds.

The overview names four kinds of stuck:

1. **Needs you.** Anything left for the person, all at the same level: an open question (AskUserQuestion), an open permission prompt, or a session line with `n` > 0 (a command to run, a mail to write, a purchase, a sign-in). The reason names which of these it is. The context shows the question with its options, the tool and its command, or the line's `ask`; with `n` > 1 it reads "3 things left for you" and the jump leads to them. On 2026-10-17, 4 of 15 session lines had `n` > 0.
2. **Limit.** A `rate_limit` API-error record is the last thing in the transcript. The context shows the reset time when the error carries one, and how long the session has been held.
3. **Error.** Any other API or auth error as the last record. The reason is the error type (overloaded, auth, server).
4. **Hung.** Busy, but not moving by the rule in "What signals show that a session is moving?" for 10 minutes (`config.json`, like today's `stuck_after_minutes`). The context shows the last tool and how long ago. It replaces today's `stuck`; counting background work as movement removes the 328 subagent and background false alarms.

Not stuck:

- **Waiting on tests, a subagent or a background job** is moving, shown in the movement sign as "waiting on: tests, 12 min". A long tool run reads the same way, replacing the `tool` flag.
- **Idle** shows "idle 14 min" and no kind. It never reads as "your turn": 68% of idle spells were ended by another session or a job.
- Error loops, a session off track, and a session waiting on a peer that never replies are left to the movement sign.
- A full disk is one banner across the page, not a per-session kind.

Today's flags (`stuck`, `waiting`, `ready`, `tool`) keep being computed as they are, because the chime reads them; only the page shows the kinds.

**Timeouts.** The person wants nothing that waits for them to time out. Claude Code documents a two-minute countdown only for removals on critical paths in auto mode (`CLAUDE_CODE_DISABLE_DANGEROUS_RM_TIMEOUT`); the docs give no timeout for other Bash prompts, so the 44 denied prompts are not yet explained. Questions carry `askUserQuestionTimeout` in the person's Claude Code settings. Both are settings outside agentview, not part of the overview.

Replacing dialogs altogether with one list of things left for the person was ruled out of scope for this map.
