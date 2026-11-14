# 15: The press path reads a bounded log

**What to fix:** since 13, a `ready` record carries the raw What-ships lines (15-25 KB each, was ~200 bytes), and deskwatch's recover() parses the whole, unbounded merge-desk.log every 3 s (deskwatch.py ~290, ~320). Over months that grows into seconds of CPU per poll. Keep an index of the last record per key (or rotate the log and carry forward the live keys' last records), so a poll reads a bounded amount. Found in 13's round 2 (Britta, class b).

**Also from 12 (Wanda, F5):** deskscan's on_desk reads the page and the log twice per candidate PR; the same bounded read should serve it.

**Blocked by:** 13

**Claimed by:** Emil 2026-11-14 02:11

**Status:** in-progress

- [ ] A poll reads a bounded amount of the log whatever its length (test with a 50 MB log)
- [ ] `desk status` and recover() give the same answers before and after a rotation
