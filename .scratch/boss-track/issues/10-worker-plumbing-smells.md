# 10: Small smells in the worker plumbing

**What to build (standards review of PR 40, judgement calls):** rename `fleet._ROLES` (now holds concierge panes and boss owners; key `at` unexplained); `_read_panes` returns nothing and writes a global, so return the pair instead; `objectives.workers(track, sessions, is_concierge, owner_of, boss_panes)` takes three callbacks where one `owned_by_track(m)` predicate would do; the "concierge" task test sits beside `IDLE_TASKS` and could join it.

**Status:** ready-for-agent
