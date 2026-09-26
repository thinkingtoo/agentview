"""Which sessions the page calls a boss.

claude-boss marks a boss with `pm/.boss-sessions/<session id>` under the
config dir, and every one of its hooks acts on that file alone. The page
reads the same file, so the badge means what the hooks mean: a registered
boss. A session that only typed `/boss` and never registered is not one.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import claude

SID = "11111111-1111-1111-1111-111111111111"


class Marker(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.markers = self.cfg / "pm" / ".boss-sessions"
        self.cwd = "/work/demo"
        self.transcripts = self.cfg / "projects" / "-work-demo"
        self.transcripts.mkdir(parents=True)

    def rec(self, sid=SID):
        return {"sessionId": sid, "cwd": self.cwd, "pid": os.getpid(),
                "kind": "interactive", "status": "idle"}

    def transcript(self, *lines, sid=SID):
        (self.transcripts / f"{sid}.jsonl").write_text("\n".join(lines) + "\n")

    def test_a_session_with_a_marker_is_a_boss(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).write_text("lead-engine\n")
        self.assertTrue(claude.session(self.rec(), self.cfg)["boss"])

    def test_typing_boss_without_registering_is_not_a_boss(self):
        self.transcript('{"type":"user","message":{"content":'
                        '"<command-name>/boss</command-name>"}}')
        self.assertFalse(claude.session(self.rec(), self.cfg)["boss"])

    def test_a_symlink_or_a_directory_is_not_a_marker(self):
        self.markers.mkdir(parents=True)
        (self.cfg / "elsewhere").write_text("lead-engine\n")
        (self.markers / SID).symlink_to(self.cfg / "elsewhere")
        self.assertFalse(claude.session(self.rec(), self.cfg)["boss"])
        other = "22222222-2222-2222-2222-222222222222"
        (self.markers / other).mkdir()
        self.assertFalse(claude.session(self.rec(other), self.cfg)["boss"])

    def test_a_session_id_that_is_a_path_is_never_a_boss(self):
        (self.cfg / "pm").mkdir()
        (self.cfg / "pm" / "x").write_text("")
        self.assertFalse(claude.is_boss("../x", self.cfg))
        self.assertFalse(claude.is_boss("", self.cfg))

    def test_the_team_is_who_a_registered_boss_messaged(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).write_text("")
        self.transcript('{"type":"assistant","message":{"content":[{"type":"tool_use",'
                        '"id":"t1","name":"SendMessage","input":{"to":"Rosalie",'
                        '"message":"go"}}]}}')
        self.assertEqual(claude.session(self.rec(), self.cfg)["team"], ["Rosalie"])


if __name__ == "__main__":
    unittest.main()
