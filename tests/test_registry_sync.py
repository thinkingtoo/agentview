#!/usr/bin/env python3
"""The vendored registry.py must be cc-agent-names' copy, byte for byte.

Run: python3 -m unittest tests.test_registry_sync

The master lives in cc-agent-names (scripts/registry.py). The test looks for a
checkout beside this repo, or at $CC_AGENT_NAMES_ROOT, and skips when there is
none -- CI has only this repo. Fix a failure with scripts/vendor-registry.
"""
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDORED = REPO / "providers" / "registry.py"
MASTER = Path(os.environ.get("CC_AGENT_NAMES_ROOT") or REPO.parent / "cc-agent-names") \
    / "scripts" / "registry.py"


class RegistrySync(unittest.TestCase):

    def test_header_says_where_it_came_from(self):
        second = VENDORED.read_text(encoding="utf-8").splitlines()[1]
        self.assertTrue(second.startswith("# vendored from cc-agent-names@"), second)

    @unittest.skipUnless(MASTER.is_file(), f"no master copy at {MASTER}")
    def test_matches_the_master_copy(self):
        lines = VENDORED.read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertEqual("".join(lines[:1] + lines[2:]), MASTER.read_text(encoding="utf-8"),
                         "vendored registry.py drifted; run scripts/vendor-registry")


if __name__ == "__main__":
    unittest.main()
