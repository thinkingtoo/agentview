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

    def test_each_session_keeps_its_pid(self):
        peers = [{**PEERS[0], "pid": 4242}]
        snap = snapshot.build(peers, TMUX, WEZ, CLIENTS, 100, "boot")
        self.assertEqual(snap["sessions"][0]["pid"], 4242)

    def test_only_tmux_sessions_hosting_claude_are_kept_with_every_pane(self):
        self.assertEqual([t["name"] for t in self.snap["tmux"]], ["23"])
        panes = self.snap["tmux"][0]["windows"][0]["panes"]
        self.assertEqual([p["sessionId"] for p in panes], ["aaa", "bbb", ""])

    def test_it_records_which_terminals_were_running(self):
        snap = snapshot.build(PEERS, TMUX, WEZ, CLIENTS, 1, "b", terminals=[20, 10])
        self.assertEqual(snap["terminals"], [10, 20])

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

    def test_a_terminal_that_died_this_boot_is_a_reboot_of_its_own(self):
        # 2026-09-24: WezTerm crashed at 15:38 and took five sessions with it;
        # the button offered the 14:15 state of the boot before.
        snaps = [{"taken_at": 1, "boot_id": "a"},
                 {"taken_at": 5, "boot_id": "now", "terminals": [8993]},
                 {"taken_at": 7, "boot_id": "now", "terminals": [8993]},
                 {"taken_at": 9, "boot_id": "now", "terminals": [462900]}]
        self.assertEqual(snapshot.choose(snaps, "now", [462900])["taken_at"], 7)

    def test_a_terminal_still_running_is_not_a_reason(self):
        snaps = [{"taken_at": 1, "boot_id": "a"},
                 {"taken_at": 5, "boot_id": "now", "terminals": [8993]},
                 {"taken_at": 9, "boot_id": "now", "terminals": [8993, 777]}]
        self.assertEqual(snapshot.choose(snaps, "now", [8993, 777])["taken_at"], 1)

    def test_a_crash_is_offered_for_a_day_after_it(self):
        # 2026-09-25: Thursday 15:38's crash still on the button at 09:10 Friday.
        day, crash = snapshot.OFFER, {"taken_at": 1000}
        self.assertTrue(snapshot.still_offered(crash, 10, 1000 + day - 1))
        self.assertFalse(snapshot.still_offered(crash, 10, 1000 + day))

    def test_an_earlier_boot_is_offered_for_a_day_after_the_reboot(self):
        # A week switched off does not age out the state it went down with.
        old = {"taken_at": 1000}
        self.assertTrue(snapshot.still_offered(old, 900000, 900000 + 60))
        self.assertFalse(snapshot.still_offered(old, 900000, 900000 + snapshot.OFFER))
        self.assertFalse(snapshot.still_offered(None, 0, 0))

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


class UnseenTmux(unittest.TestCase):
    def test_a_session_hosting_claude_with_no_client_is_unseen(self):
        self.assertEqual(snapshot.unseen_tmux(PEERS, TMUX, []), ["23"])

    def test_an_attached_session_is_seen(self):
        self.assertEqual(snapshot.unseen_tmux(PEERS, TMUX, CLIENTS), [])

    def test_a_tmux_session_without_claude_is_left_alone(self):
        self.assertNotIn("9", snapshot.unseen_tmux(PEERS, TMUX, []))


class Closed(unittest.TestCase):
    # Two saves this boot and one from the boot before. Cleo left at 200,
    # Tobias is still running, Old belongs to the reopen button.
    SNAPS = [
        {"boot_id": "b0", "taken_at": 50, "sessions": [{"sessionId": "old", "name": "Old", "cwd": "/"}]},
        {"boot_id": "b1", "taken_at": 100, "sessions": [
            {"sessionId": "aaa", "name": "Cleo", "cwd": "/p", "flags": ""},
            {"sessionId": "ccc", "name": "Tobias", "cwd": "/home", "flags": ""}]},
        {"boot_id": "b1", "taken_at": 200, "sessions": [
            {"sessionId": "aaa", "name": "Cleo", "cwd": "/p", "flags": "--model opus"},
            {"sessionId": "ccc", "name": "Tobias", "cwd": "/home", "flags": ""},
            {"sessionId": "ddd", "name": "Dora", "cwd": "/q", "flags": ""}]},
        {"boot_id": "b1", "taken_at": 300, "sessions": [
            {"sessionId": "ccc", "name": "Tobias", "cwd": "/home", "flags": ""}]},
    ]

    def test_a_session_this_boot_had_and_no_longer_runs_is_closed(self):
        got = snapshot.closed(self.SNAPS, "b1", {"ccc"})
        self.assertEqual([r["sessionId"] for r in got], ["aaa", "ddd"])

    def test_the_last_sighting_is_what_it_comes_back_with(self):
        cleo = snapshot.closed(self.SNAPS, "b1", {"ccc"})[0]
        self.assertEqual((cleo["flags"], cleo["last_seen"]), ("--model opus", 200))

    def test_one_you_dismissed_stays_gone(self):
        got = snapshot.closed(self.SNAPS, "b1", {"ccc"}, skip={"aaa"})
        self.assertEqual([r["sessionId"] for r in got], ["ddd"])

    def test_a_conversation_its_own_terminal_replaced_is_not_closed(self):
        # /clear, or /resume inside the session: same process, new id.
        live = [{"sessionId": "new", "name": "Cleo", "cwd": "/p", "pid": 7, "started": 150}]
        snaps = [dict(s) for s in self.SNAPS]
        snaps[2] = {**snaps[2], "sessions": [{**snaps[2]["sessions"][0], "pid": 7}]
                    + snaps[2]["sessions"][1:]}
        got = snapshot.closed(snaps, "b1", {"ccc", "new"}, live=live)
        self.assertEqual([r["sessionId"] for r in got], ["ddd"])

    def test_without_a_pid_the_same_name_and_place_started_earlier_is_the_same_terminal(self):
        live = [{"sessionId": "new", "name": "Cleo", "cwd": "/p", "pid": 7, "started": 150}]
        got = snapshot.closed(self.SNAPS, "b1", {"ccc", "new"}, live=live)
        self.assertEqual([r["sessionId"] for r in got], ["ddd"])

    def test_a_name_handed_out_again_later_does_not_hide_the_closed_one(self):
        live = [{"sessionId": "new", "name": "Cleo", "cwd": "/p", "pid": 7, "started": 250}]
        got = snapshot.closed(self.SNAPS, "b1", {"ccc", "new"}, live=live)
        self.assertEqual([r["sessionId"] for r in got], ["aaa", "ddd"])

    def test_the_last_boot_is_left_to_the_reopen_button(self):
        got = snapshot.closed(self.SNAPS, "b1", set())
        self.assertNotIn("old", [r["sessionId"] for r in got])


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
