# 20: A log rotation that fails, fails once and quietly

**What to fix:** class c follow-ups from ticket 15 (Emil), all in desk.history()'s rotation:
1. The directory fsync and the floor write sit outside the try, so a failure there raises after the replace.
2. A stripped `ready` whose JSON round-trip fails (hand-edited log only) aborts every rotation and each poll rescans: carry the raw line.
3. os.link succeeding and os.replace failing leaves one archive link per poll.
4. Between MAX_LOG and twice the floor, each history() takes both locks: check the floor before the lock.
5. A huge floor file silently stops rotation.
Also: nothing prunes the merge-desk.log.<time> archives (decide: keep N, or leave to the person).

**Blocked by:** 15

**Claimed by:** Sven 2026-11-14 10:41

**Status:** in-progress

- [ ] A failing fsync or floor write after the replace leaves a working log and no exception to the caller (test)
- [ ] A hand-edited ready that does not round-trip is carried as its raw line (test)
- [ ] A failing replace leaves no archive link behind, poll after poll (test)
- [ ] A floor file with a nonsense size is ignored, rotation goes on (test)
