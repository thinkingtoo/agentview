# 12: Found items are classified Merge or Deploy like handed-over ones

**What to build:** the daily scan (08, deskscan.add) adds found items as plain Merge items. Once 05's classifier exists (deskships.read), a found PR on a repo whose base branch deploys (tiroir/apex, tiroir/telemasterclass) must become a Deploy item with its "What ships" sub-list, exactly as a hand-over does. Found during 08 and 05 (Rania, Chiara, 2026-11-14).

**Blocked by:** 05, 08

**Claimed by:** Wanda 2026-11-14 01:49

**Status:** done

- [x] A found PR on a deploying repo is a Deploy item with What ships; on a test-only repo it stays Merge
- [x] A gh failure while classifying a found PR leaves it out of the desk for that day (logged), never a Merge item by default
- [x] Tests use a fake `gh` on PATH, never the real GitHub

**Done (Wanda, 2026-11-14):** merged into dev as 8e5b4ce, pushed; live since 02:04:02 (MainPID 3812054, 43 claude processes before and after). Tarek added default-deny: a found item is pressable only on a repo in `desk_found_repos` (default sheaf and agentview), documented in the README. Opus rounds: /home/tiroir/Projects/agentview-wt/wanda-12-opus-1.md, -2.md, both GO. The first scan on the new code runs at the next due time (the day was spent at 01:58:22 by the old code; it found nothing).
