import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet

SHELVES = [
    "/home/alice",
    "/home/alice/Projects",
    "/home/alice/Projects/clients",
]


class ResolveProject(unittest.TestCase):
    def test_directory_below_a_shelf_is_a_project(self):
        self.assertEqual(
            fleet.resolve_project("/home/alice/Projects/maple", SHELVES), "maple"
        )

    def test_deeper_path_keeps_the_client_and_the_project(self):
        # Dmitri works in acme/site. Naming it "site" loses the client
        # and collides with the unrelated site project.
        self.assertEqual(
            fleet.resolve_project(
                "/home/alice/Projects/clients/acme/site", SHELVES
            ),
            "acme › site",
        )

    def test_a_session_sitting_on_a_shelf_has_no_project(self):
        # Four of ten sessions live in ~ or ~/Projects. They are real work
        # with no project, not projects called "Projects".
        self.assertIsNone(fleet.resolve_project("/home/alice/Projects", SHELVES))
        self.assertIsNone(fleet.resolve_project("/home/alice", SHELVES))

    def test_the_deepest_shelf_wins(self):
        # ~/Projects and ~/Projects/clients both contain this path.
        self.assertEqual(
            fleet.resolve_project(
                "/home/alice/Projects/clients/northwind", SHELVES
            ),
            "northwind",
        )

    def test_a_path_under_no_shelf_falls_back_to_its_own_name(self):
        self.assertEqual(fleet.resolve_project("/opt/central-app", SHELVES),
                         "central-app")


class Summary(unittest.TestCase):
    """What the page pulls out of a transcript.

    Pointed at `scan_cached`, which is what the page calls. These assertions
    used to run against a second, full-file scanner that nothing called -- so
    they passed while the live one carried a bug for the whole of its life.
    """

    def write(self, records):
        import json, tempfile
        from pathlib import Path as P
        path = P(tempfile.mkdtemp()) / "t.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        fleet._cache.clear()
        return path

    def test_the_last_ai_title_wins(self):
        # Claude retitles a session as it learns what it is about.
        path = self.write([
            {"type": "ai-title", "aiTitle": "Debugging a hook"},
            {"type": "user", "message": {}},
            {"type": "ai-title", "aiTitle": "Cloud instance naming plugin"},
        ])
        self.assertEqual(fleet.scan_cached(path)["title"],
                         "Cloud instance naming plugin")

    def test_last_prompt_and_branch_come_back_too(self):
        path = self.write([
            {"type": "user", "message": {}, "gitBranch": "feat/old"},
            {"type": "last-prompt", "lastPrompt": "fix the deploy"},
            {"type": "user", "message": {}, "gitBranch": "dev"},
            {"type": "last-prompt", "lastPrompt": "now ship it"},
        ])
        summary = fleet.scan_cached(path)
        self.assertEqual(summary["prompt"], "now ship it")
        self.assertEqual(summary["branch"], "dev")

    def test_a_headless_session_has_no_title(self):
        # Verified: the nightly-report routine's transcripts carry a giant
        # prompt and no ai-title record at all.
        path = self.write([
            {"type": "last-prompt", "lastPrompt": "# Nightly report routine\n\nYou are..."},
        ])
        summary = fleet.scan_cached(path)
        self.assertEqual(summary["title"], "")
        self.assertTrue(summary["prompt"].startswith("# Nightly report"))

    def test_a_detached_head_is_not_a_branch(self):
        path = self.write([{"type": "user", "message": {}, "gitBranch": "HEAD"}])
        self.assertEqual(fleet.scan_cached(path)["branch"], "")


class Paths(unittest.TestCase):
    def test_hidden_directories_are_not_projects(self):
        # ~/.claude/plans is under the ~ shelf, so it used to resolve as a
        # project called ".claude" and outvote the real answer when guessing.
        self.assertIsNone(fleet.resolve_project("/home/alice/.claude/plans", SHELVES))
        self.assertIsNone(fleet.resolve_project("/home/alice/.config/foo", SHELVES))

    def test_scratch_space_is_not_a_project(self):
        self.assertIsNone(fleet.resolve_project(
            "/tmp/claude-1000/-home-tiroir/abc/scratchpad", SHELVES))

    def test_a_deep_path_keeps_only_client_and_project(self):
        # A file deep inside a repo must land on the same label as the repo,
        # not grow a breadcrumb per directory.
        self.assertEqual(
            fleet.resolve_project(
                "/home/alice/Projects/clients/acme/site/src/app",
                SHELVES),
            "acme › site")


class Flags(unittest.TestCase):
    """Which of five things a session is, and how sure the page is of it."""

    def flag(self, status, **kw):
        kw.setdefault("quiet", 0.0)
        kw.setdefault("after", 5)
        return fleet.classify(status, kw.pop("quiet"), kw.pop("after"), **kw)

    def test_a_finished_session_you_have_not_read_is_ready(self):
        self.assertEqual(self.flag("idle", unseen=True), "ready")

    def test_and_once_you_have_read_it_it_is_nothing(self):
        self.assertIsNone(self.flag("idle", unseen=False))

    def test_a_background_job_still_running_does_not_stop_it_being_ready(self):
        # `shell` is idle with a job the session started still running. The
        # turn is over either way, which is what ready is about.
        self.assertEqual(self.flag("shell", unseen=True), "ready")

    def test_a_dialog_that_names_what_it_wants_is_waiting_at_once(self):
        # No grace: Claude Code only writes `waitingFor` when something is
        # really on screen asking.
        self.assertEqual(
            self.flag("waiting", named=True, waiting_for=0.01, waiting_after=0.33),
            "waiting")

    def test_an_unnamed_wait_still_serves_its_grace(self):
        # A `/btw` helper sits in `waiting` for a few seconds and names
        # nothing. A flag that fires on those is one you learn to ignore.
        self.assertIsNone(
            self.flag("waiting", named=False, waiting_for=0.01, waiting_after=0.33))
        self.assertEqual(
            self.flag("waiting", named=False, waiting_for=9.0, waiting_after=0.33),
            "waiting")

    def test_working_is_not_a_claim_on_you(self):
        self.assertIsNone(self.flag("busy", quiet=0.2))

    def test_busy_and_silent_with_nothing_running_is_stuck(self):
        self.assertEqual(self.flag("busy", quiet=17.0), "stuck")

    def test_but_not_while_a_call_is_in_flight(self):
        self.assertIsNone(self.flag("busy", quiet=17.0, in_flight=0.5, tool_after=20))
        self.assertEqual(
            self.flag("busy", quiet=17.0, in_flight=34.0, tool_after=20), "tool")


class LastWords(unittest.TestCase):
    def test_the_last_line_is_the_one_that_asks(self):
        # A turn opens with what it did and ends with what it wants.
        said = fleet.last_words("Imported 412 works.\n\nTwo had no composer — "
                                "want me to guess or skip them?")
        self.assertEqual(said, "Two had no composer — want me to guess or skip them?")

    def test_tables_and_headings_are_not_something_anyone_was_told(self):
        self.assertEqual(
            fleet.last_words("Done.\n\n## Results\n\n| a | b |\n| 1 | 2 |"), "Done.")

    def test_code_blocks_are_skipped(self):
        self.assertEqual(
            fleet.last_words("Run this:\n```bash\nls -la\n```"), "Run this:")

    def test_markdown_emphasis_is_not_quoted_back_at_you(self):
        self.assertEqual(fleet.last_words("**Pushed** to `dev`."), "Pushed to dev.")

    def test_a_bullet_is_still_a_sentence(self):
        self.assertEqual(fleet.last_words("Two left:\n- fix the tests"),
                         "fix the tests")

    def test_a_long_ending_is_cut_to_its_last_sentence(self):
        long = ("I looked at every file in the repository and read the whole "
                "history of the branch and considered several options. " * 2)
        got = fleet.last_words(long + "Shall I go ahead?")
        self.assertEqual(got, "Shall I go ahead?")

    def test_one_endless_sentence_is_cut_with_an_ellipsis(self):
        got = fleet.last_words("word " * 80)
        self.assertLessEqual(len(got), 140)
        self.assertTrue(got.endswith("…"))

    def test_a_session_that_has_said_nothing_says_nothing(self):
        self.assertEqual(fleet.last_words(""), "")
        self.assertEqual(fleet.last_words("```\njust code\n```"), "")
