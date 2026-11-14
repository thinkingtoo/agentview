# 35: The desk tests carry their own classifier

**What to fix:** the desk tests depend on the machine's `~/.claude/routines/branch_deploys.py` (and on pyyaml). Found in ticket 30 (Leire, Codex review /home/tiroir/Projects/agentview-wt/leire-30-codex-1.md, finding b): the structure-digest test skips on a machine whose classifier is old, and with no classifier at all 17 tests in tests/test_deskwatch.py (`Ships`) fail.
- Give the desk tests a stub classifier fixture that mirrors the classifier's OUTPUT format (name line, `  N: hint`, `  = structure sha256:<32 hex>`, `  ! could not parse: ...`, exit 1 and no output when nothing fires), not its internals: ticket 29 (Hilde) is changing branch_deploys.py (aliased-key digest).
- tests/test_deskships.py and tests/test_deskwatch.py use it, so they no longer read the real classifier.
- At most one test runs the real classifier: marked, skipping cleanly when it is missing, old or without pyyaml. It also compares the stub's output with the real one on the fixtures, so a drift shows.
- Tests only; a test that exposes a real bug stops the ticket and goes to Tarek.

**Blocked by:** 30

**Claimed by:** Leire 2026-11-14

**Status:** done

- [x] a stub classifier fixture in tests/, same output format as the real one (leire/35 2781443: tests/stub_classifier.py; mutation dropping the indent from its digest fails the key-moved test)
- [x] test_deskwatch passes with `HOME` on an empty directory (no classifier): no failure, no skip but the real-classifier test (HOME on an empty dir: test_deskships + test_deskwatch 132 tests OK, skipped=1 which is the real-classifier test; real HOME: 132 OK, 0 skipped)
- [x] test_deskships passes the same way (same run)
- [x] one real-classifier test, marked, skips cleanly; it compares the stub with the real output (RealClassifier in tests/test_deskships.py: skipUnless usable; compares exit code and output, digest hash normalised, on 3 fixture sets)
