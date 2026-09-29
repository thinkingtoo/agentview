import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import retention

DAY = 86400
NOW = 1_790_000_000


def transcript(project, sid, entrypoint, age_days, records=None):
    """A transcript shaped like the ones on this machine (2026-09-29): the
    first records carry no entrypoint, the first user record does."""
    project.mkdir(parents=True, exist_ok=True)
    lines = records if records is not None else [
        {"type": "queue-operation", "operation": "enqueue", "sessionId": sid},
        {"type": "ai-title", "aiTitle": "t", "sessionId": sid},
        {"type": "user", "entrypoint": entrypoint, "sessionId": sid,
         "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "entrypoint": entrypoint, "sessionId": sid},
    ]
    path = project / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in lines))
    folder = project / sid / "subagents"
    folder.mkdir(parents=True)
    (folder / "agent-a1.jsonl").write_text("{}\n")
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


class Prune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projects"
        self.proj = self.root / "-home-u-p"

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_old_headless_transcript_goes_with_its_folder_and_an_old_interactive_one_stays(self):
        headless = transcript(self.proj, "11111111-aaaa", "sdk-cli", 45)
        interactive = transcript(self.proj, "22222222-bbbb", "cli", 45)

        gone = retention.prune(self.root, NOW, days=30)

        self.assertEqual(gone, [headless])
        self.assertFalse(headless.exists())
        self.assertFalse((self.proj / "11111111-aaaa").exists())
        self.assertTrue(interactive.exists())
        self.assertTrue((self.proj / "22222222-bbbb" / "subagents" / "agent-a1.jsonl").exists())

    def test_a_headless_transcript_touched_within_30_days_stays(self):
        young = transcript(self.proj, "33333333-cccc", "sdk-cli", 29)

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(young.exists())

    def test_an_interactive_conversation_carried_on_headless_stays(self):
        sid = "44444444-dddd"
        mixed = transcript(self.proj, sid, None, 60, records=[
            {"type": "user", "entrypoint": "cli", "sessionId": sid},
            {"type": "user", "entrypoint": "sdk-cli", "sessionId": sid},
        ])

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(mixed.exists())

    def test_a_transcript_that_names_no_entrypoint_stays(self):
        sid = "55555555-eeee"
        unknown = transcript(self.proj, sid, None, 60, records=[
            {"type": "queue-operation", "sessionId": sid},
            {"type": "ai-title", "aiTitle": "t", "sessionId": sid},
        ])
        with open(unknown, "a") as fh:
            fh.write('{"entrypoint": "sdk-cli", "cut off mid-wri')
        os.utime(unknown, (NOW - 60 * DAY, NOW - 60 * DAY))

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(unknown.exists())

    def test_links_are_never_followed(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "keep.txt").write_text("x")
        sid = "77777777-aaaa"
        headless = transcript(self.proj, sid, "sdk-cli", 45)
        (self.proj / sid / "subagents" / "agent-a1.jsonl").unlink()
        (self.proj / sid / "subagents").rmdir()
        (self.proj / sid).rmdir()
        (self.proj / sid).symlink_to(outside)
        (self.proj / "88888888-bbbb.jsonl").symlink_to(self.proj / "gone.jsonl")

        retention.prune(self.root, NOW, days=30)

        self.assertTrue((outside / "keep.txt").exists())
        self.assertTrue(headless.exists())

    def test_a_dry_run_names_what_would_go_and_deletes_nothing(self):
        headless = transcript(self.proj, "66666666-ffff", "sdk-cli", 45)

        would = retention.prune(self.root, NOW, days=30, dry_run=True)

        self.assertEqual(would, [headless])
        self.assertTrue(headless.exists())
        self.assertTrue((self.proj / "66666666-ffff" / "subagents").exists())


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "projects" / "-home-u-p"
        self.headless = transcript(self.proj, "99999999-cccc", "sdk-cli", 45)
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR")
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = retention.main(["retention.py", *args], now=NOW)
        return code, out.getvalue()

    def test_without_a_mode_nothing_is_deleted(self):
        code, _ = self.run_main()

        self.assertEqual(code, 2)
        self.assertTrue(self.headless.exists())

    def test_a_dry_run_prints_each_transcript_and_a_total(self):
        code, out = self.run_main("--dry-run")

        self.assertEqual(code, 0)
        self.assertIn(str(self.headless), out)
        self.assertIn("would delete 1 headless transcript", out)
        self.assertTrue(self.headless.exists())

    def test_delete_removes_it_and_says_so(self):
        code, out = self.run_main("--delete")

        self.assertEqual(code, 0)
        self.assertIn("deleted 1 headless transcript", out)
        self.assertFalse(self.headless.exists())


if __name__ == "__main__":
    unittest.main()
