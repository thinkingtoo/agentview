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
        headless = transcript(self.proj, "11111111-aaaa-aaaa-aaaa-111111111111", "sdk-cli", 45)
        interactive = transcript(self.proj, "22222222-bbbb-bbbb-bbbb-222222222222", "cli", 45)

        gone = retention.prune(self.root, NOW, days=30)

        self.assertEqual(gone, [headless])
        self.assertFalse(headless.exists())
        self.assertFalse((self.proj / "11111111-aaaa-aaaa-aaaa-111111111111").exists())
        self.assertTrue(interactive.exists())
        self.assertTrue((self.proj / "22222222-bbbb-bbbb-bbbb-222222222222" / "subagents" / "agent-a1.jsonl").exists())

    def test_a_headless_transcript_touched_within_30_days_stays(self):
        young = transcript(self.proj, "33333333-cccc-cccc-cccc-333333333333", "sdk-cli", 29)

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(young.exists())

    def test_an_interactive_conversation_carried_on_headless_stays(self):
        sid = "44444444-dddd-dddd-dddd-444444444444"
        mixed = transcript(self.proj, sid, None, 60, records=[
            {"type": "user", "entrypoint": "cli", "sessionId": sid},
            {"type": "user", "entrypoint": "sdk-cli", "sessionId": sid},
        ])

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(mixed.exists())

    def test_a_transcript_that_names_no_entrypoint_stays(self):
        sid = "55555555-eeee-eeee-eeee-555555555555"
        unknown = transcript(self.proj, sid, None, 60, records=[
            {"type": "queue-operation", "sessionId": sid},
            {"type": "ai-title", "aiTitle": "t", "sessionId": sid},
        ])

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(unknown.exists())

    def test_a_line_that_cannot_be_read_keeps_the_transcript(self):
        # The broken line could have been the one that said cli.
        headless = transcript(self.proj, "13131313-aaaa-aaaa-aaaa-131313131313", "sdk-cli", 60)
        with open(headless, "a") as fh:
            fh.write('{"type": "user", "entrypoint": "cli", "mess\n["not", "a", "record"]\n')
        os.utime(headless, (NOW - 60 * DAY, NOW - 60 * DAY))

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(headless.exists())

    def test_a_transcript_written_to_while_it_is_judged_stays(self):
        # A headless session resumed by hand just as the job reaches it.
        headless = transcript(self.proj, "14141414-aaaa-aaaa-aaaa-141414141414", "sdk-cli", 60)

        def resumed(path):
            with open(path, "a") as fh:
                fh.write(json.dumps({"type": "user", "entrypoint": "cli"}) + "\n")

        self.assertEqual(retention.prune(self.root, NOW, days=30, each=resumed), [])
        self.assertTrue(headless.exists())
        self.assertTrue((self.proj / "14141414-aaaa-aaaa-aaaa-141414141414").exists())

    def test_one_session_that_cannot_be_deleted_does_not_stop_the_rest(self):
        stuck = transcript(self.proj, "15151515-aaaa-aaaa-aaaa-151515151515", "sdk-cli", 60)
        after = transcript(self.proj, "16161616-aaaa-aaaa-aaaa-161616161616", "sdk-cli", 60)
        locked = self.proj / "15151515-aaaa-aaaa-aaaa-151515151515" / "subagents"
        locked.chmod(0o500)
        try:
            gone = retention.prune(self.root, NOW, days=30)
        finally:
            locked.chmod(0o700)

        self.assertEqual(gone, [after])
        self.assertTrue(stuck.exists())
        self.assertFalse(after.exists())

    def test_links_are_never_followed(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "keep.txt").write_text("x")
        sid = "77777777-aaaa-aaaa-aaaa-777777777777"
        headless = transcript(self.proj, sid, "sdk-cli", 45)
        (self.proj / sid / "subagents" / "agent-a1.jsonl").unlink()
        (self.proj / sid / "subagents").rmdir()
        (self.proj / sid).rmdir()
        (self.proj / sid).symlink_to(outside)
        (self.proj / "88888888-bbbb.jsonl").symlink_to(self.proj / "gone.jsonl")

        retention.prune(self.root, NOW, days=30)

        self.assertTrue((outside / "keep.txt").exists())
        self.assertTrue(headless.exists())

    def test_a_project_reached_through_a_link_is_left_alone(self):
        real = Path(self.tmp.name) / "real-project"
        headless = transcript(real, "12121212-aaaa-bbbb-cccc-121212121212", "sdk-cli", 45)
        self.root.mkdir(parents=True)
        (self.root / "-linked").symlink_to(real)

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(headless.exists())

    def test_only_a_transcript_named_by_a_session_id_is_considered(self):
        memory = transcript(self.proj, "memory", "sdk-cli", 45)
        (self.proj / "memory" / "notes.md").write_text("x")

        self.assertEqual(retention.prune(self.root, NOW, days=30), [])
        self.assertTrue(memory.exists())
        self.assertTrue((self.proj / "memory" / "notes.md").exists())

    def test_a_dry_run_names_what_would_go_and_deletes_nothing(self):
        headless = transcript(self.proj, "66666666-ffff-ffff-ffff-666666666666", "sdk-cli", 45)

        would = retention.prune(self.root, NOW, days=30, dry_run=True)

        self.assertEqual(would, [headless])
        self.assertTrue(headless.exists())
        self.assertTrue((self.proj / "66666666-ffff-ffff-ffff-666666666666" / "subagents").exists())


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "projects" / "-home-u-p"
        self.headless = transcript(self.proj, "99999999-cccc-cccc-cccc-999999999999", "sdk-cli", 45)
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
