"""The tile tags a concierge beside its name; the name itself stays the bare address.

claude-boss stamps a concierge's tmux pane `@worker_role concierge`. The page
reads that for a chip, as it reads the boss marker for the boss chip, and
nothing that resolves a name ever sees the chip. The tmux case runs a private
server on its own TMUX_TMPDIR, with TMUX unset and `-t` on every call.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_columns import Base, session


class Tag(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, fleet, "_pane_roles", fleet._pane_roles)
        fleet._pane_roles = lambda now=None: frozenset({"main:0.2"})

    def test_a_session_in_a_concierge_pane_is_tagged_and_keeps_its_name(self):
        t = self.tile(session("a", name="Fatima", tmux="main:0.2"))
        self.assertIn("concierge", t["tags"])
        self.assertEqual(t["name"], "Fatima")

    def test_a_worker_in_another_pane_is_not(self):
        t = self.tile(session("a", name="Greta", tmux="main:0.3"))
        self.assertNotIn("concierge", t["tags"])
        self.assertEqual(t["name"], "Greta")

    def test_a_session_with_no_pane_is_not(self):
        self.assertNotIn("concierge", self.tile(session("a", name="Greta"))["tags"])

    def test_no_tag_reaches_the_name_the_page_sends_messages_to(self):
        rows = self.members(session("a", name="Fatima", tmux="main:0.2"))
        self.assertEqual(rows[0]["name"], "Fatima")
        self.assertNotIn("[", rows[0]["name"])


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class RealTmux(unittest.TestCase):
    def test_the_pane_target_the_registry_records_is_the_one_the_tag_reads(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
        env["TMUX_TMPDIR"] = tmp
        sh = Path(tmp) / "run.sh"
        sh.write_text('set -e\n'
                      'tmux -f /dev/null new-session -d -s t -x 80 -y 24 sleep 60\n'
                      'tmux display-message -p -t t:0.0 "#{socket_path}"\n'
                      'tmux set-option -p -t t:0.0 @worker_role concierge\n')
        out = subprocess.run(["bash", str(sh)], capture_output=True, text=True, timeout=30, env=env)
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], env=env, capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.strip().startswith(tmp), out.stdout)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.pop("TMUX", None)
        os.environ["TMUX_TMPDIR"] = tmp
        self.assertEqual(fleet._pane_roles(now=1e9 + 100), frozenset({"t:0.0"}))


if __name__ == "__main__":
    unittest.main()
