# 29: An unreadable workflows folder is not "nothing fires"

**What to fix:** class b left by ticket 22 (Codex review of 22, /home/tiroir/Projects/agentview-wt/carmen-22-codex-3.md, run by Pablo; citations verified at b087c9e, finding 1 still holds at ~/.claude 2295355), all in routines/branch_deploys.py main() and read_workflow():
1. `if not wf.is_dir(): return 1` reads an unlistable `.github/workflows` as "no workflows", exit 1, "nothing fires": a symlink loop (workflows -> workflows) or a `.github` with chmod 000. Ticket 22 meant an unlistable directory to be a could-not-parse line with exit 0. Only a folder that is really absent (ENOENT, ENOTDIR) is exit 1.
2. The directory listing runs before SIGALRM is armed, so a hostile repo with a huge workflows directory costs unbounded time and memory. Bring the listing under the same deadline; when it runs out, one could-not-parse line for the directory, exit 0.
3. Class c: `read_workflow` checks realpath and os.stat, then calls os.open without O_NOFOLLOW, a TOCTOU window. Add O_NOFOLLOW (the path is already resolved, so a symlink there means a swap since the check).

4. Class a (Codex on 25, bram-25-codex-2.md, finding 4, reproduced by Pablo): `structure_digest` registers value nodes only, so an aliased mapping key is not a graph node: `on: push` + `&k a: x` + `b: *k` and `on: push` + `a: x` + `b: y` give the same digest. A changed structure must change it.
5. Class b (same review, finding 5): the unlistable-directory line is printed outside the broken-pipe handling; with stdout closed on a reader that left it exits 120.

**Blocked by:** 22, 25

**Claimed by:** Hilde 2026-11-14 20:10

**Status:** done

- [x] `.github/workflows` as a symlink loop gives a could-not-parse line for the directory, exit 0 (test) (test_a_workflows_symlink_loop_is_could_not_parse_not_exit_1, red then green)
- [x] `.github` with chmod 000 gives the same (test) (test_a_dot_github_with_no_permission_is_could_not_parse_not_exit_1)
- [x] A checkout with no `.github`, or no `workflows` inside it, is still exit 1, no output (existing tests) (test_no_workflows_folder_is_still_exit_1 (absent, empty .github, a plain file))
- [x] A listing that outruns BRANCH_DEPLOYS_TIME_LIMIT gives a could-not-parse line for the directory, exit 0, and the alarm is disarmed (test) (test_a_listing_that_outruns_the_time_limit_is_could_not_parse_and_disarms_the_alarm (itimer back to 0))
- [x] A workflow path swapped for a symlink after the check is refused by os.open (O_NOFOLLOW; test) (test_a_workflow_swapped_for_a_symlink_after_the_check_is_refused_by_open)
- [x] The aliased-key pair above gives two different digests, and documents without aliased keys keep their digest (test; old vs new --full identical on the five repos) (test_an_aliased_mapping_key_is_a_node_of_the_structure_digest; 20 runs old vs new identical)
- [x] The unlistable-directory line survives a reader that left: exit 0, no stderr (test) (test_the_unlistable_workflows_line_survives_a_reader_that_left)
- [x] Default output byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo, old vs new (20 runs (5 repos x main/dev x default/--full) byte-identical, rc included)
- [x] History check clean; one Codex review on the final diff (clean; Codex review 2 on c2db455: no a or b (hilde-29-codex-2.md); round 1 NO-GO fixed (listing/alarm gap, class b); its class a (a regular file named workflows is exit 1) kept on purpose)


## Done (Hilde, 2026-11-14)
Branch hilde/29 in ~/.claude at c2db455 (not merged; waiting for Tarek). Tests: routines/tests/test_branch_deploys.py 78 passed. Class c left: an unclosed /dev/null fd in _emit (pre-existing, short-lived CLI), and test_no_workflows_folder_is_still_exit_1 runs the script twice per assertion.

## Decisions
- A `.github/workflows` that exists but is a plain file stays exit 1 (Codex round 1 called it class a; Tarek, 2026-11-14): GitHub reads no workflows from a file, so nothing fires.

## Open notes (class c, not fixed)
- `_emit` in routines/branch_deploys.py opens /dev/null for `dup2` and never closes the descriptor (pre-existing code, short-lived CLI).
- `test_no_workflows_folder_is_still_exit_1` runs the script twice per assertion, taking the return code and stdout from different processes.
