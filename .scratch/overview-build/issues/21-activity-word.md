# 21: One word next to a working session's name

**What to build:** a working tile shows, next to the session's name, one word for what it is doing ("reviewing", "testing", "editing"), the way a stopped tile shows "ready" or "Needs you". The owner asked for it on 2026-10-21: a boss session was green while it waited on a Codex review, and the tile could have said "reviewing".

**Blocked by:** 20 (the "waiting" word comes from it)

**Claimed by:** Tarek 2026-10-21

**Status:** in review (branch `overview/20-waiting`)

## The rule (`fleet.activity_of`)

- Stuck (Needs you, Error, Hung, Limit) or at rest: no word; the kind or nothing says it.
- Waiting on its own job with its turn over (ticket 20): `waiting`.
- A call in flight: a file or web tool says its kind (`editing`, `reading`, `researching`, `messaging`, `delegating` for a subagent call); a command, a skill or an unknown tool is read for the work it names, first match: review, tests, build, deploy, push, merge, commit, install; else `running`.
- No call: `delegating` while a subagent writes; a job or a Codex run read for its work the same way, else `waiting`; else `thinking`.
- The provider hands over the tool of the newest call in flight (`doingTool`, Claude only); a provider without it is read for its `doing` text only.

## Boxes

- [x] The word per shape, through `roster()` with a fake provider (`tests/test_activity_word.py`, 9 tests)
- [x] The page shows it next to the name: green, and blue with a dashed edge for `waiting`; escaped as text
- [ ] Seen on the live page on real sessions
