"""The folder a Claude session is placed by is the one it was launched in.

`providers/base.py` promises it, and the overview's project assignment leans
on it: a session that `cd`s elsewhere must stay in the column it started in.
Claude Code's peer file holds the launch folder; the transcript follows the
session around. The reader must hand over the first, not the second.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import claude

SID = "33333333-3333-3333-3333-333333333333"


class LaunchFolder(unittest.TestCase):
    def test_a_session_that_moved_to_another_folder_is_still_placed_by_where_it_started(self):
        cfg = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cfg, True)
        folder = cfg / "projects" / "-work-demo"
        folder.mkdir(parents=True)
        moves = [{"type": "user", "cwd": "/work/demo", "message": {"content": "start"}},
                 {"type": "user", "cwd": "/work/other", "message": {"content": "moved"}}]
        (folder / f"{SID}.jsonl").write_text("".join(json.dumps(m) + "\n" for m in moves))
        rec = {"sessionId": SID, "cwd": "/work/demo", "pid": os.getpid(),
               "kind": "interactive", "status": "idle"}
        self.assertEqual(claude.session(rec, cfg)["cwd"], "/work/demo")


if __name__ == "__main__":
    unittest.main()
