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


class Attach(unittest.TestCase):
    def setUp(self):
        self.proc = Path(tempfile.mkdtemp())
        self.opened, self.ran, self.routes = [], [], {}
        self.delay = 0
        jump._ATTACHING.clear()
        for target, new in (
                ("jump.open_tab", self.open_tab),
                ("jump._run", self.run_step),
                ("jump.route_for", lambda pid, tmux="": self.routes.get(pid)),
                ("jump._x_windows", lambda: []),
                ("subprocess.run", self.refuse),
                ("subprocess.Popen", self.refuse)):
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

    def test_the_wait_for_a_new_tab_ends(self):
        with mock.patch("jump.ATTACH_GRACE", 0.05):
            self.attach()
            time.sleep(0.08)
            self.attach()
        self.assertEqual(len(self.opened), 2)

    def test_something_that_is_not_a_job_id_launches_nothing(self):
        done = self.attach("--help")
        self.assertFalse(done["ok"])
        self.assertEqual(self.opened, [])


PTS_54 = 34870          # `/dev/pts/54` as the kernel numbers it
STAT = "{pid} (claude) S 1859 {pid} 742539 {tty} -1 4194304 1 0 0 0 1 2 0 0 20 0 15 0 1640779 0 0"


class FakeRegistry(unittest.TestCase):
    """A registry folder and a process table that are only on paper."""

    def setUp(self):
        base = Path(tempfile.mkdtemp())
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

    def test_clicking_a_background_session_attaches_it_by_its_job(self):
        self.background()
        with mock.patch("jump.attach", return_value={"ok": True}) as attach:
            done = self.provider.jump(self.provider.find(SID))
        self.assertEqual(done, {"ok": True})
        attach.assert_called_once_with(JOB, sid=SID, name="Harbor review", proc=self.proc)

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


class Click(FakeRegistry):
    """`POST /api/jump` end to end, on a server of its own: port 0, throwaway
    stores, a fake registry behind the real Claude provider, and nowhere a
    terminal could be reached."""

    def setUp(self):
        super().setUp()
        import fleet, log, seen, server
        tmp = Path(tempfile.mkdtemp())
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

    def post(self, body, headers=None):
        headers = {"Content-Type": "application/json", "X-Fleet": "1", **(headers or {})}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}/api/jump",
            data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def tile(self):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/roster"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())["columns"][0]["sessions"][0]

    def unread(self):
        return self.seen.ready(f"claude:{SID}", 1790000000000, self.seen.load())

    def test_the_session_is_unread_until_a_jump_reaches_it(self):
        self.background(statusUpdatedAt=1790000000000)
        self.assertEqual(self.tile()["flag"], "ready")
        self.assertTrue(self.unread())

    def test_a_jump_that_reached_the_terminal_marks_the_session_seen(self):
        self.background(statusUpdatedAt=1790000000000)
        status, done = self.post({"key": f"claude:{SID}"})
        self.assertEqual((status, done["ok"]), (200, True))
        self.assertFalse(self.unread())
        self.assertNotEqual(self.tile()["flag"], "ready")

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
