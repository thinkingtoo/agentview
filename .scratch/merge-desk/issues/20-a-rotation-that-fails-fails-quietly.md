# 20: A log rotation that fails, fails once and quietly

**What to fix:** class c follow-ups from ticket 15 (Emil), all in desk.history()'s rotation:
1. The directory fsync and the floor write sit outside the try, so a failure there raises after the replace.
2. A stripped `ready` whose JSON round-trip fails (hand-edited log only) aborts every rotation and each poll rescans: carry the raw line.
3. os.link succeeding and os.replace failing leaves one archive link per poll.
4. Between MAX_LOG and twice the floor, each history() takes both locks: check the floor before the lock.
5. A huge floor file silently stops rotation.
Also: nothing prunes the merge-desk.log.<time> archives (decide: keep N, or leave to the person).

**Waiting (Tarek, 2026-11-14):** built on branch Sven/20 head 5729841, Sonnet r1 GO (Sven-20-sonnet-1.md); owes one Codex run at 15:00+ on that head, then merge. Handoff: see handoff-Sven-2026-11-14.md.

**Blocked by:** 15

**Claimed by:** Sven 2026-11-14 10:41

**Status:** done

- [x] A failing fsync or floor write after the replace leaves a working log and no exception to the caller (test)
- [x] A hand-edited ready that does not round-trip is carried as its raw line (test)
- [x] A failing replace leaves no archive link behind, poll after poll (test)
- [x] A floor file with a nonsense size is ignored, rotation goes on (test)

Evidence (Sven, branch Sven/20, 5729841): `python3 -I -m unittest discover -s tests -p test_deskrotate.py` in the worktree: 17 tests OK; the 5 new ones fail on origin/dev's desk.py (4 failures, 2 errors). Sonnet review 1: GO, /home/tiroir/Projects/agentview-wt/Sven-20-sonnet-1.md. Archives: not pruned, README says to delete by hand. Codex run (Lucas, 2026-11-14 15:0x, head 5729841): GO, no findings, /home/tiroir/Projects/agentview-wt/Sven-20-codex-2.md. Merged into dev as 9e24980 (origin/dev merged into the branch first; tests.test_deskrotate + tests.test_desk 77 OK, load 3.5). Restart: 15:07, no `pressing` without a result, cgroup held only python3 (server.py), MainPID 617994 -> 3178524, HEAD = origin/dev = 9e24980, 200 on 8765, claude count 45 -> 45, `desk` startup line /usr/bin/gh. `hooks/desk status` differed in one line only: install:sheafmd waiting, re-pinned ff5aaf7 -> 4acd660 by AgentView's scan at 15:07:12 (sheaf main moved); nothing pressed. Class c left: a floor file that can never be written plus a carried log still above MAX_LOG rotates at every poll (README says so).
