# 05: Deploy items show what ships before the press

**What to build:** an item whose repo's base branch deploys (`~/.claude/routines/branch_deploys.py <checkout> <branch>` exit 0 with deploy, publish or upload lines) is a Deploy item: `- [ ] Deploy …`, with a "What ships" sub-list of those lines and the commits that go out. The press merges as in 03. v1 repos: `tiroir/apex`, `tiroir/telemasterclass`.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] A repo whose workflows only test stays a Merge item
- [ ] The "What ships" lines are read at hand-over and again just before the merge; a change between the two refuses the press and says what changed
