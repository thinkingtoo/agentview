# 08: The daily scan finds PRs nobody handed over, and tidies the desk

**What to build:** once a day, the open PRs of the repos AgentView knows that are green, mergeable and more than a day old, and that no session handed over, become items marked "found, no recommendation yet". Merged and withdrawn items older than a day leave the page.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] A found item never carries a recommendation of its own
- [ ] Tidying never touches an item with an open comment thread
