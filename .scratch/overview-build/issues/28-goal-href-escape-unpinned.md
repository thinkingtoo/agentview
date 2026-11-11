# 28: Pin the escaping of the goal url in "goal ↗"

**What to build:** a check in `goal_pass` (`tests/ui_smoke.py`) where `track.goal.url` starts with `http://127.0.0.1:` and carries a quote or markup, and the link's `href` reads back exactly as sent, with no attribute or element built from it. A mutation that drops `esc()` around `g.url` in `goalLinkOf` (`index.html`) must fail it.

**Found in:** Codex review 1 of PR #18 (Opus fallback, run by Tarek, 2026-11-11), class c. The url comes from the hub's port and sheaf's roots (`goal_page.py`), whose paths are `quote()`d, so the risk is low.

**Blocked by:** None.

**Status:** needs-triage

- [ ] The check exists and fails with `esc()` dropped -- evidence: the mutation
