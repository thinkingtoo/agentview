# 02: tests/test_push.py leaves its temp dirs behind

**What to fix:** `Once.setUp` in `tests/test_push.py` (line 202) makes a directory with `tempfile.mkdtemp()` for `push.json` and never removes it, so each of the seven tests in `Once` (lines 213 to 263) leaves one directory in `TMPDIR`. Give that site a cleanup (`self.addCleanup(shutil.rmtree, self.state.parent, True)` on the next line, plus `import shutil`), the form ticket 01 used, without changing what any test checks. It is the only `mkdtemp` in the file. Small: seven directories of one small file each per run, against the 67,052 of ticket 01.

**Blocked by:** None

**Status:** needs-triage

**Claimed by:** Mateus 2026-11-11

- [ ] `python3 -m unittest discover -s tests -p test_push.py` with `TMPDIR` pointed at a fresh empty dir leaves 0 entries there (7 today)
- [ ] No test's assertions change (diff shows only the cleanup line and the import)
- [ ] The full suite, run on t-compute with a private `TMPDIR`, leaves 0 entries there; if it does not, name the modules that leave the rest (see below)

**Evidence:**

1. Piotr, 2026-11-11, full suite on t-compute at `0d702ac` (`python3 -m unittest discover -s tests`, Python 3.14.4, "Ran 2355 tests in 360.076s", "OK (skipped=4)"), private `TMPDIR`: 13 entries left in it, temp dirs with `push.json`, attributed to `tests/test_push.py`. Nothing was written to `/tmp`.
2. Rania, 2026-11-11, on origin/dev `02ff8ce`, laptop, `tests.test_push` alone with `PYTHONDONTWRITEBYTECODE=1` and a fresh empty `TMPDIR`: "Ran 27 tests", OK, 7 directories left: 5 hold `push.json`, 2 are empty (the tests where nothing is written: `test_with_nothing_included_nothing_is_read_or_sent` and `test_without_a_token_nothing_is_sent` never reach the state file).
3. So test_push accounts for 7 of the 13. The other 6 are not located. Run alone the same way, these modules leave 0: `test_archive`, `test_codex`, `test_movement_procs`, `test_reopen`, `test_meaning`, `test_starter_walk` (the files whose `mkdtemp` has no cleanup on the next line; each registers it further down). The full suite was not run on the laptop (load 23 at the time); locating the other 6 needs the full run on t-compute with the entries' names and contents listed, or each module run alone there.
