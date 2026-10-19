"""A background session is reached by attaching to it, once.

`claude --bg` sessions live in the daemon and have no terminal. What shows one
is a separate `claude attach <id>` in some window, so the jump is either to
that window or, when nobody is attached, a new tab that attaches. Two windows
on one conversation would both write to it, so "once" is the whole point.

Nothing here touches a real terminal: the process table is a folder of fake
`cmdline` files, the places a route would be run and a tab opened are
recorders, and any real subprocess fails the test. Names and ids are invented.
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jump
import test_columns
from providers import claude
from test_columns import session
from test_providers import Fake

JOB = "3f9a0c2e"
SID = "5b1d2c3e-aaaa-bbbb-cccc-000000000001"
PANE_ROUTE = {"steps": [["wezterm", "cli", "--no-auto-start", "activate-pane", "--pane-id", "42"]],
              "window_pid": 99816}


class AttachBase(unittest.TestCase):
    """The places a route would be run and a tab opened are recorders."""
    fake_route = True           # `route_for` answers from `self.routes`; False: the real one

    def setUp(self):
        self.proc = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.proc, True)
        self.opened, self.ran, self.routes = [], [], {}
        self.delay = 0
        jump._ATTACHING.clear()
        fakes = [
            ("jump.open_tab", self.open_tab),
            ("jump._run", self.run_step),
            ("jump._x_windows", lambda: []),
            ("subprocess.run", self.refuse),
            ("subprocess.Popen", self.refuse)]
        if self.fake_route:
            fakes.append(("jump.route_for", lambda pid, tmux="": self.routes.get(pid)))
        for target, new in fakes:
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)

    def refuse(self, *a, **kw):
        raise AssertionError(f"a test reached a real process: {a}")

    def open_tab(self, argv, cwd=None):
        time.sleep(self.delay)                  # the moment wezterm takes
        self.opened.append(argv)
        return {"ok": True, "ran": ["spawn"], "pane": "9"}

    def run_step(self, argv, timeout=4):
        self.ran.append(argv)
        return mock.Mock(returncode=0, stdout="", stderr="")

    def viewer(self, pid, *argv):
        """A process `claude attach ...` in the fake process table."""
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "cmdline").write_bytes(
            b"\0".join(a.encode() for a in ("/home/alice/.local/bin/claude", "attach", *argv)) + b"\0")

    def attach(self, job=JOB, **kw):
        return jump.attach(job, sid=SID, name=kw.pop("name", "Harbor review"), proc=self.proc, **kw)


class Attach(AttachBase):
    def test_a_session_nobody_is_attached_to_gets_one_new_tab(self):
        done = self.attach()
        self.assertTrue(done["ok"])
        (argv,) = self.opened
        self.assertEqual((Path(argv[0]).name, argv[1:]), ("claude", ["attach", JOB]))

    def test_two_quick_clicks_open_one_tab(self):
        # The second click lands while the first tab is still being opened: no
        # process shows the attach yet, so nothing but the guard can tell.
        self.delay = 0.2
        got = []
        clicks = [threading.Thread(target=lambda: got.append(self.attach())) for _ in range(2)]
        for c in clicks:
            c.start()
        for c in clicks:
            c.join()
        self.assertEqual(len(self.opened), 1)
        self.assertTrue(all(g["ok"] for g in got))
        self.assertEqual(sorted(g.get("did", "") for g in got), ["", "opening"])

    def test_a_click_just_after_the_first_still_opens_nothing_more(self):
        # The new claude has no process the table can show for a moment.
        self.attach()
        self.assertEqual(self.attach()["did"], "opening")
        self.assertEqual(len(self.opened), 1)

    def test_once_it_is_attached_the_click_goes_to_the_window_showing_it(self):
        self.viewer(700, JOB)
        self.routes[700] = PANE_ROUTE
        done = self.attach()
        self.assertTrue(done["ok"])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.ran, PANE_ROUTE["steps"])

    def test_a_viewer_no_window_can_be_raised_for_is_refused_not_duplicated(self):
        self.viewer(700, JOB)
        done = self.attach()
        self.assertFalse(done["ok"])
        self.assertIn("already attached", done["reason"])
        self.assertEqual(self.opened, [])

    def test_a_viewer_started_by_hand_with_part_of_the_name_counts(self):
        # `claude attach` takes "part of the session name" in place of the id.
        self.viewer(700, "harbor")
        self.routes[700] = PANE_ROUTE
        self.attach()
        self.assertEqual(self.opened, [])

    def test_a_name_fragment_two_sessions_share_may_be_either_so_it_opens_nothing(self):
        # `harbor` could be this session or the other. A window raised for the
        # wrong one is worse than none, and a tab for it would put a second
        # copy on a conversation that may be shown already.
        self.viewer(700, "harbor")
        self.routes[700] = PANE_ROUTE
        done = self.attach(rivals=["Harbor build"])
        self.assertFalse(done["ok"])
        self.assertIn("may be", done["reason"])
        self.assertEqual((self.ran, self.opened), ([], []))

    def test_a_fragment_that_is_ambiguous_only_later_still_opens_nothing(self):
        # The same `claude attach harbor` was this session's alone while no
        # other session had "harbor" in its name; a second one starting turns
        # the viewer from sure into doubtful, and the click must not open a copy.
        self.viewer(700, "harbor")
        self.routes[700] = PANE_ROUTE
        self.attach()
        self.assertEqual(self.ran, PANE_ROUTE["steps"])          # sure: its window is raised
        self.ran.clear()
        self.assertFalse(self.attach(rivals=["Harbor build"])["ok"])
        self.assertEqual((self.ran, self.opened), ([], []))

    def test_a_viewer_started_with_the_session_id_counts(self):
        self.viewer(700, SID[:13])
        self.routes[700] = PANE_ROUTE
        self.attach()
        self.assertEqual(self.opened, [])

    def test_a_viewer_of_another_session_does_not(self):
        self.viewer(700, "9d8c7b6a")
        self.viewer(701, "orchard")
        self.attach()
        self.assertEqual(len(self.opened), 1)

    def test_a_process_table_that_cannot_be_read_has_no_viewers(self):
        self.assertEqual(jump.attaches(self.proc / "gone"), [])

    def test_a_process_that_only_mentions_attach_is_not_a_viewer(self):
        (self.proc / "800").mkdir()
        (self.proc / "800" / "cmdline").write_bytes(
            b"\0".join(a.encode() for a in ("vim", "attach", JOB)) + b"\0")
        self.attach()
        self.assertEqual(len(self.opened), 1)

    def test_a_launch_that_failed_can_be_tried_again(self):
        with mock.patch("jump.open_tab", return_value={"ok": False, "reason": "wezterm cli spawn failed", "ran": []}):
            self.assertFalse(self.attach()["ok"])
        self.assertTrue(self.attach()["ok"])
        self.assertEqual(len(self.opened), 1)

    def test_a_tab_opened_long_ago_is_forgotten(self):
        jump._ATTACHING["aaaaaaaa"] = jump._now() - 3600     # it was due then
        self.attach()
        self.assertEqual(list(jump._ATTACHING), [JOB])

    def test_the_wait_for_a_new_tab_ends(self):
        with mock.patch("jump.ATTACH_GRACE", 0.05):
            self.attach()
            time.sleep(0.08)
            self.attach()
        self.assertEqual(len(self.opened), 2)

    def test_a_tab_whose_window_is_still_starting_is_waited_for_longer(self):
        # With no WezTerm running the tab is only started, not confirmed: no
        # pane id comes back, and `claude attach` has no process until the
        # window is up. Five seconds is too short for that.
        cold = lambda argv, cwd=None: self.opened.append(argv) or {"ok": True, "ran": ["wezterm start"]}
        with mock.patch("jump.open_tab", cold), mock.patch("jump.ATTACH_GRACE", 0.05):
            self.attach()
            time.sleep(0.08)
            self.assertEqual(self.attach().get("did"), "opening")
        self.assertEqual(len(self.opened), 1)

    def test_something_that_is_not_a_job_id_launches_nothing(self):
        for bad in ("--help", None, 12345678, ["3f9a0c2e"]):
            self.assertFalse(self.attach(bad)["ok"], bad)
        self.assertEqual(self.opened, [])

    def test_a_name_or_id_that_is_not_text_matches_nothing_and_stops_nothing(self):
        self.viewer(700, "harbor")
        self.routes[700] = PANE_ROUTE
        self.assertTrue(self.attach(name=7, rivals=[None, 3, ["x"]])["ok"])
        self.assertEqual(len(self.opened), 1)


class TmuxViewer(AttachBase):
    """A `claude attach` started by hand inside a tmux pane. Its pty belongs to
    tmux, so no WezTerm pane has it: what leads to a window is the tmux session
    the pane is in and the client attached to that. The real `route_for` runs;
    the terminals it would ask are described, not asked."""
    fake_route = False
    PANE_SHELL = 650            # the pane's own shell, an ancestor of the viewer
    ASKED = ["tmux", "display-message", "-p", "-t", "%7",
             "#{pane_pid}\t#{session_name}:#{window_id}.#{pane_id}"]

    def setUp(self):
        super().setUp()
        self.said = {tuple(self.ASKED): f"{self.PANE_SHELL}\tmain:@3.%7\n"}
        self.ancestry = [("claude", 700), ("bash", self.PANE_SHELL), ("tmux: server", 600)]
        for target, new in (
                ("jump.tty_of", lambda pid: "/dev/pts/9"),
                ("jump.ancestry_of", lambda pid, depth=12: self.ancestry),
                ("jump.wezterm_panes", lambda: [{"pane_id": 42, "tty_name": "/dev/pts/3", "term_pid": 99816}]),
                ("jump.tmux_clients", lambda: [{"client_tty": "/dev/pts/3", "session": "main"}]),
                ("jump.konsole_apps", lambda: [])):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)

    def run_step(self, argv, timeout=4):
        self.ran.append(argv)
        return mock.Mock(returncode=0, stdout=self.said.get(tuple(argv), ""), stderr="")

    def environ(self, pid, **env):
        (self.proc / str(pid)).mkdir(exist_ok=True)
        (self.proc / str(pid) / "environ").write_bytes(
            b"".join(f"{k}={v}".encode() + b"\0" for k, v in env.items()))

    def test_a_viewer_in_a_tmux_pane_is_reached_through_tmux_and_its_client(self):
        self.viewer(700, JOB)
        self.environ(700, HOME="/home/alice", TMUX_PANE="%7")
        done = self.attach()
        self.assertTrue(done["ok"])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.ran, [
            self.ASKED,
            ["tmux", "select-window", "-t", "@3"], ["tmux", "select-pane", "-t", "%7"],
            ["wezterm", "cli", "--no-auto-start", "activate-pane", "--pane-id", "42"]])

    def test_a_pane_whose_shell_is_not_above_the_viewer_is_not_believed(self):
        # Pane ids repeat from one tmux server to the next: %7 here may be some
        # other pane than the one the viewer is in.
        self.viewer(700, JOB)
        self.environ(700, TMUX_PANE="%7")
        self.said[tuple(self.ASKED)] = "777\tother:@1.%7\n"
        done = self.attach()
        self.assertFalse(done["ok"])
        self.assertIn("already attached", done["reason"])
        self.assertEqual((self.opened, self.ran), ([], [self.ASKED]))

    def test_a_viewer_outside_tmux_asks_tmux_nothing(self):
        self.viewer(700, JOB)
        self.environ(700, HOME="/home/alice")
        self.assertFalse(self.attach()["ok"])
        self.assertEqual((self.opened, self.ran), ([], []))

    def test_a_pane_id_that_is_not_one_reaches_no_command_line(self):
        self.viewer(700, JOB)
        for bad in ("-x", "%7;x", "%", "7", ""):
            self.environ(700, TMUX_PANE=bad)
            self.assertFalse(self.attach()["ok"], bad)
        self.assertEqual((self.opened, self.ran), ([], []))

    def test_a_viewer_whose_environment_cannot_be_read_is_still_never_duplicated(self):
        self.viewer(700, JOB)
        done = self.attach()
        self.assertFalse(done["ok"])
        self.assertEqual(self.opened, [])


PTS_54 = 34870          # `/dev/pts/54` as the kernel numbers it
STAT = "{pid} (claude) S 1859 {pid} 742539 {tty} -1 4194304 1 0 0 0 1 2 0 0 20 0 15 0 1640779 0 0"


class FakeRegistry(unittest.TestCase):
    """A registry folder and a process table that are only on paper."""

    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        self.cfg, self.proc = base / "claude", base / "proc"
        (self.cfg / "sessions").mkdir(parents=True)
        self.proc.mkdir()
        self.provider = claude.ClaudeProvider(self.cfg, proc=self.proc)

    def process(self, pid, tty=PTS_54, *argv):
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "stat").write_text(STAT.format(pid=pid, tty=tty) + "\n")
        if argv:
            (self.proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

    def background(self, pid=10, job=JOB, **over):
        self.process(pid, 0)
        rec = {"pid": pid, "sessionId": SID, "kind": "bg", "jobId": job, "status": "idle",
               "procStart": "1640779", "cwd": "/tmp", "name": "Harbor review"}
        rec.update(over)
        (self.cfg / "sessions" / f"{pid}.json").write_text(json.dumps(rec))


class BackgroundSessions(FakeRegistry):
    """What the Claude provider says about a `claude --bg` session."""

    def only(self):
        (got,) = self.provider.live()
        return got

    def test_a_background_session_with_no_viewer_can_be_attached(self):
        self.background()
        got = self.only()
        self.assertEqual((got["attach"], got["canJump"]), (JOB, False))

    def test_one_that_is_attached_in_a_terminal_is_jumped_to_instead(self):
        self.background()
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", JOB)
        got = self.only()
        self.assertEqual((got["attach"], got["canJump"]), ("", True))

    def test_one_attached_where_no_terminal_shows_it_is_not_attached_again(self):
        self.background()
        self.process(700, 0, "/home/alice/.local/bin/claude", "attach", "harbor")
        got = self.only()
        self.assertEqual((got["attach"], got["canJump"]), ("", False))
        self.assertIn("attached", got["noJump"])

    def test_a_peer_file_with_odd_fields_does_not_stop_the_poll(self):
        # A name that is a number or a list: the page keeps polling and the
        # other sessions keep their tiles.
        self.background(10, JOB, name=7)
        self.background(11, "9d8c7b6a", name=["Orchard build"], sessionId="7a7a7a7a-0000-0000-0000-000000000002")
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", "orchard")
        got = {s["id"]: s["attach"] for s in self.provider.live()}
        self.assertEqual(got, {SID: JOB, "7a7a7a7a-0000-0000-0000-000000000002": "9d8c7b6a"})

    def test_a_record_with_no_usable_job_id_has_nothing_to_attach(self):
        self.background(job="--help")
        self.assertEqual(self.only()["attach"], "")

    def test_a_session_at_a_terminal_has_nothing_to_attach(self):
        self.process(10)
        rec = {"pid": 10, "sessionId": SID, "kind": "interactive", "entrypoint": "cli",
               "status": "idle", "procStart": "1640779", "cwd": "/tmp", "name": "Harbor review"}
        (self.cfg / "sessions" / "10.json").write_text(json.dumps(rec))
        got = self.only()
        self.assertEqual((got["attach"], got["canJump"]), ("", True))

    def click(self):
        """What the provider does for a click, with the tab and any process stopped."""
        opened = []
        jump._ATTACHING.clear()
        with mock.patch("jump.open_tab", lambda argv, cwd=None: opened.append(argv) or {"ok": True, "ran": []}), \
                mock.patch("jump._run", lambda argv, timeout=4: self.fail(f"ran {argv}")), \
                mock.patch("jump.route_for", lambda pid, tmux="": PANE_ROUTE), \
                mock.patch("subprocess.run", side_effect=AssertionError("a real process")):
            done = self.provider.jump(self.provider.find(SID))
        return done, opened

    def test_clicking_a_background_session_opens_a_tab_attached_to_its_job(self):
        self.background()
        done, opened = self.click()
        self.assertTrue(done["ok"])
        (argv,) = opened
        self.assertEqual((Path(argv[0]).name, argv[1:]), ("claude", ["attach", JOB]))

    def test_a_fragment_both_background_sessions_share_may_be_attached_to_either(self):
        self.background(10, JOB, name="Harbor review")
        self.background(11, "9d8c7b6a", name="Harbor build", sessionId="7a7a7a7a-0000-0000-0000-000000000002")
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", "harbor")
        got = {s["name"]: (s["attach"], s["canJump"], "may be" in s["noJump"]) for s in self.provider.live()}
        self.assertEqual(got, {"Harbor review": ("", False, True), "Harbor build": ("", False, True)})

    def test_clicking_one_of_two_that_a_shared_fragment_may_show_opens_nothing(self):
        self.background(10, JOB, name="Harbor review")
        self.background(11, "9d8c7b6a", name="Harbor build", sessionId="7a7a7a7a-0000-0000-0000-000000000002")
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", "harbor")
        done, opened = self.click()
        self.assertFalse(done["ok"])
        self.assertEqual(opened, [])

    def test_a_fragment_only_one_has_is_that_ones_viewer(self):
        self.background(10, JOB, name="Harbor review")
        self.background(11, "9d8c7b6a", name="Orchard build", sessionId="7a7a7a7a-0000-0000-0000-000000000002")
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", "harbor")
        got = {s["name"]: (s["attach"], s["canJump"]) for s in self.provider.live()}
        self.assertEqual(got, {"Harbor review": ("", True), "Orchard build": ("9d8c7b6a", False)})

    def test_a_session_with_no_name_is_nobodys_fragment_match(self):
        # The page calls it "(unnamed)"; that is not a name anyone can type.
        self.background(name="")
        self.process(700, PTS_54, "/home/alice/.local/bin/claude", "attach", "named")
        self.assertEqual(self.only()["attach"], JOB)
        done, opened = self.click()
        self.assertEqual(len(opened), 1)

    def test_a_session_at_a_terminal_is_left_to_the_pane_search(self):
        self.process(10)
        rec = {"pid": 10, "sessionId": SID, "kind": "interactive", "entrypoint": "cli",
               "status": "idle", "procStart": "1640779", "cwd": "/tmp", "name": "x"}
        (self.cfg / "sessions" / "10.json").write_text(json.dumps(rec))
        self.assertIsNone(self.provider.jump(self.provider.find(SID)))


class Tile(test_columns.Base):
    """The tile's `jump`: pane, attach or none, and why none."""

    def test_a_session_at_a_terminal_jumps_to_its_pane(self):
        self.assertEqual(self.tile(session("a", canJump=True))["jump"], {"via": "pane"})

    def test_a_background_session_with_nobody_attached_says_attach(self):
        self.assertEqual(self.tile(session("a", attach=JOB))["jump"], {"via": "attach"})

    def test_a_pane_beats_an_attach(self):
        self.assertEqual(self.tile(session("a", attach=JOB, canJump=True))["jump"], {"via": "pane"})

    def test_a_session_with_nowhere_to_go_says_no_terminal(self):
        self.assertEqual(self.tile(session("a"))["jump"], {"via": "none", "reason": "no terminal"})

    def test_the_provider_may_say_why_in_its_own_words(self):
        tile = self.tile(session("a", noJump="attached, but in no window that can be raised"))
        self.assertEqual(tile["jump"], {"via": "none",
                                        "reason": "attached, but in no window that can be raised"})

    def test_a_provider_that_cannot_jump_never_offers_to_attach(self):
        got = self.tile(provider=Fake([session("a", attach=JOB)], caps={"status"}))
        self.assertEqual(got["jump"], {"via": "none", "reason": "no terminal"})


class ClickServer(FakeRegistry):
    """A server of its own, for a click to land on: port 0, throwaway stores, a
    fake registry behind the real Claude provider, and nowhere a terminal could
    be reached. `Click` and the pill tests (`test_finished_route.py`) stand on it."""

    def setUp(self):
        super().setUp()
        import fleet, log, seen, server
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "config.json").write_text("{}")
        self.seen = seen
        self.opened, self.delay = [], 0
        jump._ATTACHING.clear()
        for target, new in (("fleet.CONFIG", tmp / "config.json"),
                            ("fleet._providers", lambda: [self.provider]),
                            ("seen.store", lambda: tmp / "seen.json"),
                            ("log.LOG", tmp / "events.jsonl"),
                            ("jump.open_tab", self.open_tab),
                            ("jump._run", lambda argv, timeout=4: self.fail(f"ran {argv}")),
                            ("subprocess.run", self.refuse),
                            ("subprocess.Popen", self.refuse),
                            ("server.restorable", lambda live: None),
                            ("server.closed_now", lambda live: []),
                            ("server.coverage", lambda live: None),
                            ("providers.broken", lambda: {})):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def refuse(self, *a, **kw):
        raise AssertionError(f"a test reached a real process: {a}")

    def open_tab(self, argv, cwd=None):
        time.sleep(self.delay)
        self.opened.append(argv)
        if self.fails:
            return {"ok": False, "reason": "wezterm cli spawn failed", "ran": []}
        return {"ok": True, "ran": ["spawn"], "pane": "9"}

    fails = False

    def post(self, body, headers=None, path="/api/jump"):
        headers = {"Content-Type": "application/json", "X-Fleet": "1", **(headers or {})}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}{path}",
            data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def roster(self):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/roster"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())

    def column(self):
        return self.roster()["columns"][0]

    def tile(self):
        return self.column()["sessions"][0]

    def unread(self):
        return self.seen.ready(f"claude:{SID}", 1790000000000, self.seen.load())


class Click(ClickServer):
    """`POST /api/jump` end to end."""

    def test_the_session_is_unread_until_a_jump_reaches_it(self):
        self.background(statusUpdatedAt=1790000000000)
        self.assertEqual(self.tile()["flag"], "ready")
        self.assertTrue(self.unread())

    def test_looking_at_a_session_that_has_no_terminal_marks_it_seen(self):
        # The tile that says "no terminal" is clicked only to mark it read.
        self.background(statusUpdatedAt=1790000000000)
        status, done = self.post({"key": f"claude:{SID}"}, path="/api/seen")
        self.assertEqual((status, done), (200, {"ok": True}))
        self.assertFalse(self.unread())

    def test_a_jump_that_reached_the_terminal_marks_the_session_seen(self):
        self.background(statusUpdatedAt=1790000000000)
        status, done = self.post({"key": f"claude:{SID}"})
        self.assertEqual((status, done["ok"]), (200, True))
        self.assertFalse(self.unread())
        # Read, and idle since long before: it is a pill now, not a ready tile.
        column = self.column()
        self.assertEqual(([t["key"] for t in column["sessions"]], [p["key"] for p in column["pills"]]),
                         ([], [f"claude:{SID}"]))

    def test_a_failed_jump_leaves_the_handover_unread_and_says_why(self):
        self.background(statusUpdatedAt=1790000000000)
        self.fails = True
        status, done = self.post({"key": f"claude:{SID}"})
        self.assertEqual((status, done["ok"], done["reason"]), (200, False, "wezterm cli spawn failed"))
        self.assertTrue(self.unread())
        self.assertEqual(self.tile()["flag"], "ready")

    def test_two_quick_clicks_on_one_tile_open_one_tab(self):
        self.background(statusUpdatedAt=1790000000000)
        self.delay = 0.2
        got = []
        clicks = [threading.Thread(target=lambda: got.append(self.post({"key": f"claude:{SID}"})))
                  for _ in range(2)]
        for c in clicks:
            c.start()
        for c in clicks:
            c.join()
        self.assertEqual(len(self.opened), 1)
        self.assertEqual([status for status, _ in got], [200, 200])

    def test_a_click_that_only_waited_for_a_tab_reached_nothing_and_marks_nothing(self):
        # The first tab may have died; this click did not reach a terminal.
        self.background(statusUpdatedAt=1790000000000)
        jump._ATTACHING[JOB] = jump._now() + jump.ATTACH_GRACE
        status, done = self.post({"key": f"claude:{SID}"})
        self.assertEqual((status, done["ok"], done["did"]), (200, True, "opening"))
        self.assertTrue(self.unread())
        self.assertEqual(self.opened, [])

    def test_the_guard_is_todays_a_local_page_with_the_fleet_header(self):
        self.background()
        self.assertEqual(self.post({"key": f"claude:{SID}"}, {"X-Fleet": "0"})[0], 403)
        self.assertEqual(self.post({"key": f"claude:{SID}"}, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.opened, [])

    def test_nothing_in_the_request_reaches_the_command_line(self):
        # What `claude attach` is given comes from the registry and nowhere else.
        self.background()
        self.post({"key": f"claude:{SID}", "job": "ffffffff", "id": "--help",
                   "argv": ["touch", "/tmp/owned"], "open": ["sh", "-c", "x"]})
        (argv,) = self.opened
        self.assertEqual((Path(argv[0]).name, argv[1:]), ("claude", ["attach", JOB]))

    def test_only_a_session_that_is_alive_can_be_attached(self):
        self.assertEqual(self.post({"key": f"claude:{SID}"})[0], 404)
        self.assertEqual(self.opened, [])


if __name__ == "__main__":
    unittest.main()
