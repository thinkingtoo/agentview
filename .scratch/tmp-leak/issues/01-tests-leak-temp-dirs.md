# 01: The unit tests leak temp dirs until /tmp runs out of inodes

**What to fix:** about 45 `tempfile.mkdtemp()` calls in 22 test files have no cleanup (e.g. tests/test_movement_procs.py `FakeProc.__init__`, tests/test_movement_provider.py, test_log.py, test_archive.py, test_roster_route.py, test_boss_marker.py, test_columns.py, test_attach.py). On 2026-10-19 /tmp (tmpfs, 1,048,576 inodes) ran full: 67,052 leaked `tmp????????` dirs, and `test_a_runaway_tree_is_walked_only_so_far` alone leaves about 3,600 inodes per run. Every session on the machine failed with ENOSPC until the owner cleaned up. Give every site a cleanup (`self.addCleanup(shutil.rmtree, path, True)` or a `TemporaryDirectory`), without changing what any test checks.

**Blocked by:** None

**Claimed by:** Yohana 2026-10-19 22:49

**Status:** in-progress

- [ ] `find /tmp -maxdepth 1 -name 'tmp????????' -user $USER | wc -l` is the same before and after a full unit run (run with TMPDIR pointed at a fresh empty dir and count there)
- [ ] No test's assertions change (diff shows only cleanup lines and imports)
- [ ] Full unit suite green
