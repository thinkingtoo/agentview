"""What a busy session is doing, from the tool call it is inside.

A busy row used to print your own last prompt back at you -- words you wrote
and already know. The honest answer to "where is this now" is the call that
has not come back yet.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


class Naming(unittest.TestCase):
    def test_nothing_in_flight_says_nothing(self):
        self.assertEqual(fleet.activity([]), "")

    def test_a_bash_call_uses_the_description_it_was_given(self):
        # Every Bash call carries a human description already. Nothing here
        # needs to invent a phrase when the caller wrote one.
        self.assertEqual(
            fleet.activity([("Bash", {"command": "ls -la && cat README.md",
                                      "description": "List project root and read README"})]),
            "List project root and read README")

    def test_a_bash_call_without_one_shows_the_command(self):
        self.assertEqual(
            fleet.activity([("Bash", {"command": "python3 -m unittest discover -s tests"})]),
            "Running python3 -m unittest discover -s tests")

    def test_an_edit_names_the_file_not_the_path(self):
        self.assertEqual(
            fleet.activity([("Edit", {"file_path": "/home/alice/Projects/claude-team/fleet.py"})]),
            "Editing fleet.py")

    def test_reading_several_files_at_once_is_counted(self):
        # Parallel reads are the common case, and three filenames do not fit.
        calls = [("Read", {"file_path": f"/x/{n}.py"}) for n in "abc"]
        self.assertEqual(fleet.activity(calls), "Reading 3 files")

    def test_different_tools_at_once_name_the_newest(self):
        calls = [("Read", {"file_path": "/x/a.py"}),
                 ("Bash", {"command": "git status", "description": "Show working tree status"})]
        self.assertEqual(fleet.activity(calls), "Show working tree status")

    def test_a_tool_with_no_phrase_of_its_own_says_its_name(self):
        # Being vague beats being wrong: an unknown tool is still news.
        self.assertEqual(fleet.activity([("WebSearch", {"query": "x"})]), "WebSearch")

    def test_a_long_command_is_clipped(self):
        got = fleet.activity([("Bash", {"command": "echo " + "y" * 300})])
        self.assertLessEqual(len(got), fleet.ASK_LIMIT)


class McpTools(unittest.TestCase):
    """An MCP tool's name is a wire address, not a sentence."""

    def test_the_server_prefix_is_dropped(self):
        # Live on the page: Thandi's row read
        # `mcp__gws-tiroir__gmail_users_drafts_create`.
        self.assertEqual(
            fleet.activity([("mcp__gws-tiroir__gmail_users_drafts_create", {})]),
            "Gmail users drafts create")

    def test_a_name_that_is_not_an_mcp_address_is_left_alone(self):
        self.assertEqual(fleet.activity([("WebSearch", {})]), "WebSearch")

    def test_a_malformed_address_still_says_something(self):
        self.assertEqual(fleet.activity([("mcp__onlyserver", {})]), "mcp__onlyserver")
