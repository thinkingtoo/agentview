# 29: An unreadable workflows folder is not "nothing fires"

**What to fix:** class b left by ticket 22 (Codex review of 22, /home/tiroir/Projects/agentview-wt/carmen-22-codex-3.md, run by Pablo; citations verified at b087c9e, finding 1 still holds at ~/.claude 2295355), all in routines/branch_deploys.py main() and read_workflow():
1. `if not wf.is_dir(): return 1` reads an unlistable `.github/workflows` as "no workflows", exit 1, "nothing fires": a symlink loop (workflows -> workflows) or a `.github` with chmod 000. Ticket 22 meant an unlistable directory to be a could-not-parse line with exit 0. Only a folder that is really absent (ENOENT, ENOTDIR) is exit 1.
2. The directory listing runs before SIGALRM is armed, so a hostile repo with a huge workflows directory costs unbounded time and memory. Bring the listing under the same deadline; when it runs out, one could-not-parse line for the directory, exit 0.
3. Class c: `read_workflow` checks realpath and os.stat, then calls os.open without O_NOFOLLOW, a TOCTOU window. Add O_NOFOLLOW (the path is already resolved, so a symlink there means a swap since the check).

**Blocked by:** 22, 25

**Claimed by:** Hilde 2026-11-14 20:10

**Status:** open

- [ ] `.github/workflows` as a symlink loop gives a could-not-parse line for the directory, exit 0 (test)
- [ ] `.github` with chmod 000 gives the same (test)
- [ ] A checkout with no `.github`, or no `workflows` inside it, is still exit 1, no output (existing tests)
- [ ] A listing that outruns BRANCH_DEPLOYS_TIME_LIMIT gives a could-not-parse line for the directory, exit 0, and the alarm is disarmed (test)
- [ ] A workflow path swapped for a symlink after the check is refused by os.open (O_NOFOLLOW; test)
- [ ] Default output byte-identical on monorepo, agentview, sheaf, ~/.claude, thinkingtoo, old vs new
- [ ] History check clean; one Codex review on the final diff
