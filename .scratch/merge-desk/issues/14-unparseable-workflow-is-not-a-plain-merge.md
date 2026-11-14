# 14: A workflow the classifier cannot parse is never a plain Merge

**What to fix:** a workflow file PyYAML cannot parse, with no hint word in it, comes out of `~/.claude/routines/branch_deploys.py` with no deploy line, so the desk shows a plain Merge item for a repo that may deploy. branch_deploys.py should emit a hint line for a parse failure, and the desk (deskships) treats that hint as "could not tell": a Deploy that cannot be pressed until a person looks. The script lives in the ~/.claude repo, not AgentView. Found in 05's round 4 (Chiara, class b, R4-2).

**Also (added 2026-11-14 from 13's round 2):** the classifier cuts hint lines at 140 characters (branch_deploys.py:132) and deskships._line at 180, so two long deploy lines differing only after the cut compare equal. Give full lines or a hash per line from branch_deploys.py, store and compare that in deskships; then lift 13's stopgap (a cut line refuses). And a "could not tell" refusal says what the person can do (e.g. merge on GitHub after reading the workflows, or ask the session to split the PR).

**Notes from 13's round 3 (class c, not fixed there):** `desk.flatten` folds NBSP and runs of spaces, so a change only in those compares equal; a base retarget between the check and the merge goes through (`--match-head-commit` pins the head only); `HINT_CUT` copies the classifier's 140 (a width=141 test guards it). Priority: the monorepo's tiroir-central-deploy.yml has hint lines of 155-156 chars, so until this ticket lands every such item refuses as "too long to check".

**Blocked by:** 05, 13

**Claimed by:** Samir 2026-11-14 01:52

**Status:** in-progress

- [ ] branch_deploys.py prints a parse-failure line for an unparseable workflow (its own test)
- [ ] The desk shows such a repo as "could not tell", not Merge, and refuses its press
- [ ] A deploy line longer than any cut is compared in full (or by hash): a change after character 140 refuses
- [ ] A "could not tell" refusal names what the person can do instead
