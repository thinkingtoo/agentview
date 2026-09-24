import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jump

# Shapes taken from this machine on 2026-08-27.
PANES = [
    {"pane_id": 42, "tty_name": "/dev/pts/2", "term_pid": 99816},
    {"pane_id": 10, "tty_name": "/dev/pts/89", "term_pid": 99816},
]
CLIENTS = [{"client_tty": "/dev/pts/89", "session": "39"}]
KONSOLE = [{
    "service": "org.kde.konsole-3543851",
    "term_pid": 3543851,
    "windows": [{"path": "/Windows/1", "sessions": {1: 3543961}}],
}]


class ChooseRoute(unittest.TestCase):
    def test_a_wezterm_pane_is_found_by_its_tty(self):
        route = jump.choose_route(
            tty="/dev/pts/2", ancestry=[("claude", 1036831), ("wezterm-gui", 99816)],
            tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE)
        self.assertEqual(route["steps"],
                         [["wezterm", "cli", "activate-pane", "--pane-id", "42"]])
        self.assertEqual(route["window_pid"], 99816)

    def test_a_tmux_session_selects_the_pane_then_reveals_its_client(self):
        # Halima: claude in tmux, whose only client sits in a WezTerm pane.
        # Selecting the tmux pane is useless if the WezTerm tab stays hidden.
        route = jump.choose_route(
            tty="/dev/pts/90",
            ancestry=[("claude", 2370863), ("bash", 2370230), ("tmux: server", 115907)],
            tmux="39:@39.%49", panes=PANES, clients=CLIENTS, konsole=KONSOLE)
        self.assertEqual(route["steps"], [
            ["tmux", "select-window", "-t", "@39"],
            ["tmux", "select-pane", "-t", "%49"],
            ["wezterm", "cli", "activate-pane", "--pane-id", "10"],
        ])
        self.assertEqual(route["window_pid"], 99816)

    def test_a_tmux_session_no_terminal_shows_gets_one_attached(self):
        # Selecting a pane in a tmux session nobody is attached to shows
        # nothing, and the page used to report that as a jump that worked.
        route = jump.choose_route(
            tty="/dev/pts/90",
            ancestry=[("claude", 2370863), ("bash", 2370230), ("tmux: server", 115907)],
            tmux="26:@3.%7", panes=PANES, clients=CLIENTS, konsole=KONSOLE)
        self.assertEqual(route["attach"], "26")
        self.assertIsNone(route["window_pid"])

    def test_konsole_is_matched_through_the_shell_it_owns(self):
        # Konsole reports the pid of the shell it started, never claude's own,
        # so the match has to run up the ancestry.
        route = jump.choose_route(
            tty="/dev/pts/80",
            ancestry=[("claude", 3547029), ("bash", 3543961), ("konsole", 3543851)],
            tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE)
        self.assertEqual(route["steps"], [[
            "qdbus", "org.kde.konsole-3543851", "/Windows/1",
            "org.kde.konsole.Window.setCurrentSession", "1",
        ]])
        self.assertEqual(route["window_pid"], 3543851)

    def test_a_headless_session_has_nowhere_to_go(self):
        self.assertIsNone(jump.choose_route(
            tty="/dev/null", ancestry=[("claude", 1782468), ("bash", 1782250)],
            tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE))


class TitleSteps(unittest.TestCase):
    def test_wezterm_gets_an_explicit_tab_title(self):
        # Verified: `tab_title` is a separate field that survives the OSC
        # updates Claude Code keeps writing into `title`.
        self.assertEqual(
            jump.title_steps(text="rifacendo la home", tty="/dev/pts/2",
                             ancestry=[("claude", 1036831), ("wezterm-gui", 99816)],
                             tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE),
            [["wezterm", "cli", "set-tab-title", "--pane-id", "42",
              "rifacendo la home"]])

    def test_clearing_wezterm_means_an_empty_title(self):
        self.assertEqual(
            jump.title_steps(text="", tty="/dev/pts/2",
                             ancestry=[("claude", 1036831), ("wezterm-gui", 99816)],
                             tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE),
            [["wezterm", "cli", "set-tab-title", "--pane-id", "42", ""]])

    def test_tmux_renames_the_window_it_actually_lives_in(self):
        # Not the WezTerm tab hosting the client -- that one shows whatever
        # tmux draws, so tmux is the thing to tell.
        self.assertEqual(
            jump.title_steps(text="IMSLP", tty="/dev/pts/90",
                             ancestry=[("claude", 2370863), ("tmux: server", 115907)],
                             tmux="39:@39.%49", panes=PANES, clients=CLIENTS,
                             konsole=KONSOLE),
            [["tmux", "rename-window", "-t", "@39", "IMSLP"]])

    def test_konsole_sets_the_displayed_title_role(self):
        # Verified against Konsole: role 0 is the name, role 1 is what the tab
        # shows. Setting role 0 changes nothing visible.
        self.assertEqual(
            jump.title_steps(text="pulizia", tty="/dev/pts/80",
                             ancestry=[("claude", 3547029), ("bash", 3543961),
                                       ("konsole", 3543851)],
                             tmux="", panes=PANES, clients=CLIENTS, konsole=KONSOLE),
            [["qdbus", "org.kde.konsole-3543851", "/Sessions/1",
              "org.kde.konsole.Session.setTitle", "1", "pulizia"]])

    def test_a_headless_session_has_no_title_to_set(self):
        self.assertEqual(
            jump.title_steps(text="x", tty="/dev/null",
                             ancestry=[("claude", 1782468)], tmux="",
                             panes=PANES, clients=CLIENTS, konsole=KONSOLE), [])
