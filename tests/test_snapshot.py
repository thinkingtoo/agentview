import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import snapshot

# Shapes taken from this machine on 2026-09-24: four lead-engine workers split
# in one tmux window, one conversation straight in a WezTerm tab.
PEERS = [
    {"sessionId": "aaa", "name": "Cleo", "cwd": "/p", "tty": "/dev/pts/40",
     "argv": ["claude", "--resume", "old-id"], "tmux_pane": "%49"},
    {"sessionId": "bbb", "name": "Sinead", "cwd": "/p/lead", "tty": "/dev/pts/41",
     "argv": ["claude", "--model", "opus", "--effort", "xhigh"], "tmux_pane": "%50"},
    {"sessionId": "ccc", "name": "Tobias", "cwd": "/home", "tty": "/dev/pts/1",
     "argv": ["claude"], "tmux_pane": ""},
]
TMUX = [
    {"pane_id": "%49", "session": "23", "window": 0, "window_name": "w", "layout": "L", "pane": 0, "cwd": "/p"},
    {"pane_id": "%50", "session": "23", "window": 0, "window_name": "w", "layout": "L", "pane": 1, "cwd": "/p/lead"},
    {"pane_id": "%51", "session": "23", "window": 0, "window_name": "w", "layout": "L", "pane": 2, "cwd": "/p/lead"},
    {"pane_id": "%70", "session": "9", "window": 0, "window_name": "x", "layout": "M", "pane": 0, "cwd": "/q"},
]
WEZ = [
    {"window_id": 0, "tab_id": 0, "pane_id": 0, "tty": "/dev/pts/1", "cwd": "/home"},
    {"window_id": 0, "tab_id": 1, "pane_id": 3, "tty": "/dev/pts/90", "cwd": "/home"},
    {"window_id": 2, "tab_id": 5, "pane_id": 7, "tty": "/dev/pts/91", "cwd": "/srv"},
]
CLIENTS = [{"tty": "/dev/pts/90", "session": "23"}]


class Flags(unittest.TestCase):
    def test_the_conversation_selector_is_dropped(self):
        self.assertEqual(snapshot.parse_flags(["claude", "--resume", "x", "--model", "opus"]),
                         "--model opus")
        self.assertEqual(snapshot.parse_flags(["claude", "-c", "--resume=x"]), "")

    def test_an_opening_prompt_is_not_a_flag(self):
        self.assertEqual(snapshot.parse_flags(["claude", "fix the build please"]), "")


class Build(unittest.TestCase):
    def setUp(self):
        self.snap = snapshot.build(PEERS, TMUX, WEZ, CLIENTS, 100, "boot")

    def test_each_session_knows_its_pane(self):
        by = {s["name"]: s for s in self.snap["sessions"]}
        self.assertEqual(by["Sinead"]["tmux"], {"session": "23", "window": 0, "pane": 1})
        self.assertEqual(by["Sinead"]["flags"], "--model opus --effort xhigh")
        self.assertNotIn("tmux", by["Tobias"])

    def test_only_tmux_sessions_hosting_claude_are_kept_with_every_pane(self):
        self.assertEqual([t["name"] for t in self.snap["tmux"]], ["23"])
        panes = self.snap["tmux"][0]["windows"][0]["panes"]
        self.assertEqual([p["sessionId"] for p in panes], ["aaa", "bbb", ""])

    def test_wezterm_tabs_say_what_they_showed(self):
        self.assertEqual(self.snap["wezterm"], [
            {"tabs": [{"kind": "claude", "sessionId": "ccc"},
                      {"kind": "tmux", "session": "23"}]},
            {"tabs": [{"kind": "shell", "cwd": "/srv"}]},
        ])


class Choose(unittest.TestCase):
    def test_the_last_snapshot_of_an_earlier_boot_wins(self):
        snaps = [{"taken_at": 1, "boot_id": "a"}, {"taken_at": 5, "boot_id": "a"},
                 {"taken_at": 9, "boot_id": "now"}]
        self.assertEqual(snapshot.choose(snaps, "now")["taken_at"], 5)
        self.assertIsNone(snapshot.choose(snaps[2:], "now"))

    def test_the_newest_snapshot_of_this_boot_is_what_a_shutdown_keeps(self):
        snaps = [{"taken_at": 1, "boot_id": "now"}, {"taken_at": 9, "boot_id": "a"},
                 {"taken_at": 5, "boot_id": "now"}]
        self.assertEqual(snapshot.latest(snaps, "now")["taken_at"], 5)
        self.assertIsNone(snapshot.latest(snaps[1:2], "now"))


class PanePlan(unittest.TestCase):
    SAVED = [{"index": 0, "cwd": "/p", "sessionId": "aaa"},
             {"index": 1, "cwd": "/p/lead", "sessionId": "bbb"},
             {"index": 2, "cwd": "/p/lead", "sessionId": ""}]

    def test_idle_shells_are_reused_and_missing_panes_are_split(self):
        current = {0: {"command": "bash", "busy": False}}
        self.assertEqual(snapshot.pane_plan(self.SAVED, current, set()),
                         [("resume", 0, "aaa"), ("split", "/p/lead", "bbb"), ("split", "/p/lead", "")])

    def test_a_running_session_or_a_busy_pane_is_left_alone(self):
        current = {0: {"command": "bash", "busy": True},
                   1: {"command": "bash", "busy": False},
                   2: {"command": "vim", "busy": False}}
        self.assertEqual(snapshot.pane_plan(self.SAVED, current, {"bbb"}), [])


class MissingTabs(unittest.TestCase):
    SNAP = {"wezterm": [{"tabs": [{"kind": "shell", "cwd": "/"}]},
                        {"tabs": [{"kind": "tmux", "session": "23"},
                                  {"kind": "tmux", "session": "26"},
                                  {"kind": "claude", "sessionId": "x"}]}]}

    def test_a_tmux_session_nobody_shows_is_missing(self):
        self.assertEqual(snapshot.missing_tabs(self.SNAP, CLIENTS), ["26"])

    def test_nothing_is_missing_when_every_session_has_a_client(self):
        clients = CLIENTS + [{"tty": "/dev/pts/91", "session": "26"}]
        self.assertEqual(snapshot.missing_tabs(self.SNAP, clients), [])


class TabTitle(unittest.TestCase):
    def test_one_session_reads_name_then_topic(self):
        self.assertEqual(snapshot.tab_title([{"name": "Hugo", "title": "Rapportje render-doc"}], "tribeloo"),
                         "Hugo · Rapportje render-doc")

    def test_your_own_line_beats_the_generated_title(self):
        self.assertEqual(snapshot.tab_title([{"name": "Hugo", "title": "x", "own": "invoice"}], "p"),
                         "Hugo · invoice")

    def test_several_sessions_read_project_then_names(self):
        ms = [{"name": n} for n in ("Cleo", "Sinead", "Rania", "Anwar")]
        self.assertEqual(snapshot.tab_title(ms, "thinkingtoo › lead-engine"),
                         "lead-engine · Cleo, Sinead +2")
        self.assertEqual(snapshot.tab_title(ms[:2], "tiroir"), "tiroir · Cleo, Sinead")

    def test_long_titles_are_clipped_to_the_tab_width(self):
        t = snapshot.tab_title([{"name": "Marisol", "title": "a very long topic " * 4}], "")
        self.assertLessEqual(len(t), snapshot.TITLE_MAX)
        self.assertTrue(t.endswith("…"))


if __name__ == "__main__":
    unittest.main()
