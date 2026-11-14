# 14: A workflow the classifier cannot parse is never a plain Merge

**What to fix:** a workflow file PyYAML cannot parse, with no hint word in it, comes out of `~/.claude/routines/branch_deploys.py` with no deploy line, so the desk shows a plain Merge item for a repo that may deploy. branch_deploys.py should emit a hint line for a parse failure, and the desk (deskships) treats that hint as "could not tell": a Deploy that cannot be pressed until a person looks. The script lives in the ~/.claude repo, not AgentView. Found in 05's round 4 (Chiara, class b, R4-2).

**Also (added 2026-11-14 from 13's round 2):** the classifier cuts hint lines at 140 characters (branch_deploys.py:132) and deskships._line at 180, so two long deploy lines differing only after the cut compare equal. Give full lines or a hash per line from branch_deploys.py, store and compare that in deskships; then lift 13's stopgap (a cut line refuses). And a "could not tell" refusal says what the person can do (e.g. merge on GitHub after reading the workflows, or ask the session to split the PR).

**Notes from 13's round 3 (class c, not fixed there):** `desk.flatten` folds NBSP and runs of spaces, so a change only in those compares equal; a base retarget between the check and the merge goes through (`--match-head-commit` pins the head only); `HINT_CUT` copies the classifier's 140 (a width=141 test guards it). Priority: the monorepo's tiroir-central-deploy.yml has hint lines of 155-156 chars, so until this ticket lands every such item refuses as "too long to check".

**Also from 12 (Wanda, F2):** found items (deskscan.add via deskships.read) take the same path: an unparseable workflow must make a found item "could not tell" too.

**Blocked by:** 05, 13

**Claimed by:** Samir 2026-11-14 01:52

**Status:** done

- [x] branch_deploys.py prints a parse-failure line for an unparseable workflow (its own test) (`routines/tests/test_branch_deploys.py::test_full_marks_a_workflow_that_cannot_be_parsed` and 3 more; `--full` only, default output unchanged on 4 real repos, ~/.claude 56ddfaf)
- [x] The desk shows such a repo as "could not tell", not Merge, and refuses its press (`tests/test_deskships.py::test_a_workflow_that_cannot_be_parsed_is_could_not_tell_and_names_the_file`, `tests/test_deskwatch.py::test_a_workflow_that_cannot_be_parsed_is_a_deploy_item_that_cannot_be_pressed`: Deploy item, press refused)
- [x] A deploy line longer than any cut is compared in full (or by hash): a change after character 140 refuses (`test_a_change_after_the_cut_is_a_change`, `..._no_break_space_...`, `test_a_line_made_to_look_like_a_digested_one_is_not_the_same_line` red without its guard; `test_a_long_deploy_line_that_is_unchanged_is_pressed`; a 155-char line now lists and presses)
- [x] A "could not tell" refusal names what the person can do instead (`test_every_could_not_tell_says_what_the_person_can_do`, `test_a_could_not_tell_refusal_still_says_what_to_do_after_a_long_reason`, press-time Unreadable too)

**Merged and live 2026-11-14 02:14:** dev 4e66553 (pushed), agentview.service restarted (MainPID 3997998, HTTP 200 on 8765, cgroup held server.py only before, claude 43 -> 43). ~/.claude main 9412cbb carries the classifier (default mode marks a parse failure too). Reviews: samir-14-opus-1-2.md, samir-14-opus-3.md in agentview-wt (Codex out of tokens). Open, ticket 18: non-UTF-8 exit 1, `+` in branch filters, YAML scalars, re-indentation; base-retarget race.
