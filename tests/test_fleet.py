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


class ReadSummary(unittest.TestCase):
    def write(self, records):
        import json, tempfile
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for r in records:
            fh.write(json.dumps(r) + "\n")
        fh.close()
        return fh.name

    def test_the_last_ai_title_wins(self):
        # Claude retitles a session as it learns what it is about.
        path = self.write([
            {"type": "ai-title", "aiTitle": "Debugging a hook"},
            {"type": "user", "message": {}},
            {"type": "ai-title", "aiTitle": "Cloud instance naming plugin"},
        ])
        self.assertEqual(fleet.read_summary(path)["title"],
                         "Cloud instance naming plugin")

    def test_last_prompt_and_branch_come_back_too(self):
        path = self.write([
            {"type": "user", "message": {}, "gitBranch": "feat/old"},
            {"type": "last-prompt", "lastPrompt": "fix the deploy"},
            {"type": "user", "message": {}, "gitBranch": "dev"},
            {"type": "last-prompt", "lastPrompt": "now ship it"},
        ])
        summary = fleet.read_summary(path)
        self.assertEqual(summary["prompt"], "now ship it")
        self.assertEqual(summary["branch"], "dev")

    def test_a_headless_session_has_no_title(self):
        # Verified: the nightly-report routine's transcripts carry a giant
        # prompt and no ai-title record at all.
        path = self.write([
            {"type": "last-prompt", "lastPrompt": "# Nightly report routine\n\nYou are..."},
        ])
        summary = fleet.read_summary(path)
        self.assertEqual(summary["title"], "")
        self.assertTrue(summary["prompt"].startswith("# Nightly report"))

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
