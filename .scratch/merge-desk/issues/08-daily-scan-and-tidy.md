# 08: The daily scan finds PRs nobody handed over, and tidies the desk

**What to build:** once a day, the open PRs of the repos AgentView knows that are green, mergeable and more than a day old, and that no session handed over, become items marked "found, no recommendation yet". Merged and withdrawn items older than a day leave the page.

**Blocked by:** 03, 04 (both change deskwatch.py; boss, 2026-11-14)

**Claimed by:** Rania 2026-11-14 00:45

**Status:** done

- [x] A found item never carries a recommendation of its own
  - Evidence: `tests/test_deskscan.py` `Found.test_a_found_item_says_so_on_its_own_line_and_recommends_nothing` (one line, "found by the scan, no recommendation yet", no verdict) and `test_a_pr_handed_over_is_never_also_found`; merged into dev at bd9b095, live since 01:43:19. First scan on the live desk: pending, retried at 01:58 (the 01:43 run found a cold roster).
- [x] Tidying never touches an item with an open comment thread
  - Evidence: `tests.test_deskscan.Threads` (every shape sheaf stores: inline, own line, multi-line, `<br>`, `rd-comment`, orphan, unknown status, unclosed) and `Tidy` (text after an item, swallowed items, damaged threads); five Opus bug-hunt rounds, files `rania-08-opus-1..5.md` in `/home/tiroir/Projects/agentview-wt/`.
