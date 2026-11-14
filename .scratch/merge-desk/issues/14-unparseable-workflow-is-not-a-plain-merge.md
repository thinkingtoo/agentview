# 14: A workflow the classifier cannot parse is never a plain Merge

**What to fix:** a workflow file PyYAML cannot parse, with no hint word in it, comes out of `~/.claude/routines/branch_deploys.py` with no deploy line, so the desk shows a plain Merge item for a repo that may deploy. branch_deploys.py should emit a hint line for a parse failure, and the desk (deskships) treats that hint as "could not tell": a Deploy that cannot be pressed until a person looks. The script lives in the ~/.claude repo, not AgentView. Found in 05's round 4 (Chiara, class b, R4-2).

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] branch_deploys.py prints a parse-failure line for an unparseable workflow (its own test)
- [ ] The desk shows such a repo as "could not tell", not Merge, and refuses its press
