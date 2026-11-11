# 06: A long id that SAFE accepts puts the instruction over its 2150 ceiling

**What to fix:** the id is formatted into `ASK` three times and `lines.SAFE` allows 80 characters, so the ceiling holds only for ids up to 70. Either the ceiling test uses the longest id `SAFE` accepts, or the text names the id fewer times.

**Input:** `{"session_id": "x"*71}` with the live hooks path `/home/tiroir/Projects/agentview/hooks`.

**Measured at 17386f1:** UUID (36) 2050; 71 chars 2155; 80 chars 2182.

**Failing lines:** `hooks/turn_line.py:72` `ASK.format(writer=WRITER, paste=PASTE, sid=sid)` with `lines.py:42` `SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")`.

**Class:** b (only a non-UUID id gets there).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
