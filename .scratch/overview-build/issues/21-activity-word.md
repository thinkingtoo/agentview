# 21: One word next to a working session's name

**What to build:** a working tile shows, next to the session's name, one word for what it is doing ("reviewing", "testing", "editing"), the way a stopped tile shows "ready" or "Needs you". The owner asked for it on 2026-10-21: a boss session was green while it waited on a Codex review, and the tile could have said "reviewing".

**Blocked by:** 20 (the "waiting" word comes from it)

**Claimed by:** Tarek 2026-10-21

**Status:** done

**Merged to origin/dev as** `8ebee41` (with ticket 20), 2026-10-21.

## The rule (`fleet.activity_of`)

- Stuck (Needs you, Error, Hung, Limit) or at rest: no word; the kind or nothing says it.
- Waiting on its own job with its turn over (ticket 20): `waiting`.
- A call in flight: a file or web tool says its kind (`editing`, `reading`, `researching`, `messaging`, `delegating` for a subagent call); a command, a skill or an unknown tool is read for the work it names, first match: review, tests, build, deploy, push, merge, commit, install; else `running`.
- No call: `delegating` while a subagent writes; a job or a Codex run read for its work the same way, else `waiting`; else `thinking`.
- The provider hands over the tool of the newest call in flight (`doingTool`, Claude only); a provider without it is read for its `doing` text only.

## Boxes

- [x] The word per shape, through `roster()` with a fake provider (`tests/test_activity_word.py`, 9 tests)
- [x] The page shows it next to the name: green, and blue with a dashed edge for `waiting`; escaped as text
- [x] Seen on the live page on real sessions (thinking, installing, running, waiting, 2026-10-21 22:40)

## Hunt 20-1 (Opus, 2026-10-21) on e5dbefd: NO-GO, fixed

The chime was unchanged on 24 inputs and nothing crashed. Two P1, both a wrong word on a moving tile: a busy session writing with a job open said `waiting` (the job was read before its own writes), and a session that once used a subagent said `delegating` for ever (the provider's `subQuiet` is the newest subagent file however old). Fixed: the order is call, a subagent fresher than the session and inside `hung_after`, the session's own write this minute (`thinking`), a Codex run, a job. P2 fixed: a run's label wins over a plain job's; a description's word counts only as its own verb or as the program (`Start the preview server`, `Check the build log`, `Show test output`, `Show commit history`, `pushd` are `running`); a busy status whose last word ended the turn waits on its job like an idle one (ticket 20). P2 left: a menu the person opened with a job running counts as moving, as before this diff. Smoke on e5dbefd: 395 checks OK, the owner's config untouched.
