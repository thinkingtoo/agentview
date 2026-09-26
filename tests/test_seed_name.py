"""A restored conversation gets its name back through cc-agent-names.

agentview does not write the plugin's files. It finds the installed plugin in
Claude Code's `plugins/installed_plugins.json` and runs its `bin/agent-name
set`, which remembers the name as assigned, so the resume starts under it.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import snapshot  # noqa: E402


class SeedName(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.cfg)
        self.calls = self.cfg / "calls"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old

    def install(self, with_bin=True):
        root = self.cfg / "plugins" / "cache" / "sweatshop-ai" / "agent-names" / "0.7.0"
        (root / "bin").mkdir(parents=True)
        if with_bin:
            tool = root / "bin" / "agent-name"
            tool.write_text(f'#!/bin/sh\necho "$@" >> {self.calls}\n')
            tool.chmod(0o755)
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"agent-names@sweatshop-ai": [
                {"scope": "user", "installPath": str(root), "version": "0.7.0"}]}}))

    def test_the_name_goes_through_agent_name_set(self):
        self.install()
        snapshot.seed_name("s-1", "Petra")
        self.assertEqual(self.calls.read_text().strip(), "set s-1 Petra")
        self.assertFalse((self.cfg / "agent-names").exists())   # its files stay its own

    def test_without_the_plugin_nothing_is_seeded(self):
        snapshot.seed_name("s-1", "Petra")
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.cfg / "agent-names").exists())

    def test_an_older_plugin_without_the_command_is_left_alone(self):
        self.install(with_bin=False)
        snapshot.seed_name("s-1", "Petra")
        self.assertFalse((self.cfg / "agent-names").exists())


if __name__ == "__main__":
    unittest.main()
