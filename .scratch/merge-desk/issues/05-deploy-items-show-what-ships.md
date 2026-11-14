# 05: Deploy items show what ships before the press

**What to build:** an item whose repo's base branch deploys (`~/.claude/routines/branch_deploys.py <checkout> <branch>` exit 0 with deploy, publish or upload lines) is a Deploy item: `- [ ] Deploy …`, with a "What ships" sub-list of those lines and the commits that go out. The press merges as in 03. v1 repos: `tiroir/apex`, `tiroir/telemasterclass`.

**Blocked by:** 03, 04, 10 (all change the press path in deskwatch.py; boss, 2026-11-14)

**Claimed by:** Chiara 2026-11-14 00:52

**Status:** done

- [x] A repo whose workflows only test stays a Merge item
  - Evidence: tests.test_desk Ships.test_a_repo_whose_workflows_only_test_stays_a_merge_item and tests.test_deskwatch Ships.test_a_merge_item_stays_a_merge_item_when_the_workflows_only_test (real branch_deploys.py on fixture workflows), branch chiara/05-deploy-items 8c03d67
- [x] The "What ships" lines are read at hand-over and again just before the merge; a change between the two refuses the press and says what changed
  - Evidence: tests.test_deskwatch Ships (changed workflow line, new commit, change during the UNKNOWN wait, GitHub unreadable, taken back during the read all refuse and untick; mutation: removing the check_ships call fails 6 of 10), 170 tests green across the desk test files
