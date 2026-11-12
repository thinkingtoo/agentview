# 09: Two sessions with the same name collapse into one worker

**What to build:** `objectives.workers` keys by display name, so two stamped busy sessions both named `(unnamed)` (the provider's stand-in) become one entry with the later task. Key by session key, show the name.

**Found by:** the Opus review of PR 40 (finding 2, low). Also from the review: a roster task like "concierge (standby)" is not read as a concierge when the pane mark is lost (exact match, as the ticket says); a stale "idle" table task hides a busy session that has a real `did`.

**Status:** ready-for-agent

- [ ] Two unnamed stamped workers are both listed -- evidence: test
