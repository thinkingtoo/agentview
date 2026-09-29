"""Long-lived processes the server starts go in a scope of their own.

`systemctl --user restart agentview` kills everything in the service's
cgroup. A tmux server or a WezTerm window started from the server used to be
in it. These tests pin what `scope.wrap` does, and that each place that can
start one of those goes through it -- and that nothing else does, since a
scope for a command that starts nothing lasting is noise.

The real thing (a real transient unit, a real restart) is `scripts/scope-check`.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jump
import scope
import snapshot

PREFIX = ["systemd-run", "--user", "--scope", "--quiet", "--collect"]


def ok(**kw):
    return SimpleNamespace(returncode=kw.get("returncode", 0), stdout=kw.get("stdout", ""),
                           stderr=kw.get("stderr", ""))


class Scoped(unittest.TestCase):
    """Scoping is available for the length of each test, and the event log
    is never touched."""

    def setUp(self):
        self.events = []
        for patch in (mock.patch.object(scope, "why_not", return_value=""),
                      mock.patch.object(scope.log, "event",
                                        side_effect=lambda kind, **f: self.events.append((kind, f)))):
            patch.start()
            self.addCleanup(patch.stop)


class Wrapping(Scoped):
    def test_the_command_comes_after_a_double_dash_untouched(self):
        argv = ["tmux", "new-session", "-d", "-s", "a b", "-c", "/x y", "claude --resume 1"]
        self.assertEqual(scope.wrap(argv, "tmux server"),
                         PREFIX + ["--description=agentview: tmux server", "--"] + argv)

    def test_the_caller_is_not_changed(self):
        argv = ["a", "b"]
        scope.wrap(argv, "x")
        self.assertEqual(argv, ["a", "b"])

    def test_without_a_user_manager_the_command_runs_as_it_was_and_says_why(self):
        with mock.patch.object(scope, "why_not", return_value="systemd-run exited 1: no bus"):
            self.assertEqual(scope.wrap(["wezterm", "start"], "wezterm window"), ["wezterm", "start"])
        self.assertEqual(self.events, [("scope.unavailable", {"what": "wezterm window",
                                                              "why": "systemd-run exited 1: no bus"})])

    def test_switched_off_is_quiet(self):
        with mock.patch.object(scope, "why_not", return_value="AGENTVIEW_SCOPE is off"):
            self.assertEqual(scope.wrap(["a"], "x"), ["a"])
        self.assertEqual(self.events, [])


class Asking(unittest.TestCase):
    def test_off_by_the_environment(self):
        for value in ("off", "OFF", "0", "no", "false"):
            with mock.patch.dict(os.environ, {"AGENTVIEW_SCOPE": value}):
                self.assertEqual(scope.why_not(), "AGENTVIEW_SCOPE is off")

    def test_no_systemd_run(self):
        with mock.patch.dict(os.environ, {"AGENTVIEW_SCOPE": ""}), \
                mock.patch.object(scope.shutil, "which", return_value=None):
            self.assertEqual(scope.why_not(), "no systemd-run")

    def test_the_probe_is_a_scope_around_true(self):
        with mock.patch.dict(os.environ, {"AGENTVIEW_SCOPE": ""}), \
                mock.patch.object(scope.shutil, "which", return_value="/usr/bin/systemd-run"), \
                mock.patch.object(scope.subprocess, "run", return_value=ok()) as run:
            self.assertEqual(scope.why_not(), "")
        self.assertEqual(run.call_args.args[0], PREFIX + ["--", "true"])

    def test_no_bus_says_what_systemd_run_said(self):
        with mock.patch.dict(os.environ, {"AGENTVIEW_SCOPE": ""}), \
                mock.patch.object(scope.shutil, "which", return_value="/usr/bin/systemd-run"), \
                mock.patch.object(scope.subprocess, "run",
                                  return_value=ok(returncode=1, stderr="Failed to connect to bus\n")):
            self.assertEqual(scope.why_not(), "systemd-run exited 1: Failed to connect to bus")

    def test_a_probe_that_cannot_run_is_a_reason_not_a_crash(self):
        with mock.patch.dict(os.environ, {"AGENTVIEW_SCOPE": ""}), \
                mock.patch.object(scope.shutil, "which", return_value="/usr/bin/systemd-run"), \
                mock.patch.object(scope.subprocess, "run", side_effect=OSError("no exec")):
            self.assertIn("no exec", scope.why_not())


class TmuxServer(Scoped):
    def test_only_a_new_session_can_start_the_server(self):
        new = ["tmux", "new-session", "-d", "-s", "x"]
        self.assertEqual(snapshot._tmux_argv(new)[:len(PREFIX)], PREFIX)
        self.assertEqual(snapshot._tmux_argv(new)[-len(new):], new)
        for other in (["tmux", "new-window", "-d", "-t", "=x:1"],
                      ["tmux", "respawn-pane", "-k", "-t", "=x:0.0", "claude"],
                      ["tmux", "split-window", "-d", "-t", "=x:0"],
                      ["tmux", "kill-session", "-t", "=x"],
                      ["tmux", "attach", "-t", "=x"]):
            self.assertEqual(snapshot._tmux_argv(other), other, other)

    def test_the_boot_session_that_creates_the_server_is_scoped_and_its_removal_is_not(self):
        calls = []

        def run(argv, timeout=4):
            calls.append(argv)
            return ok(returncode=1) if argv[:2] == ["tmux", "has-session"] else ok()

        with mock.patch.object(snapshot, "_run", side_effect=run):
            snapshot._wait_tmux_settled(max_wait=0)
        made = [c for c in calls if "new-session" in c]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0][:len(PREFIX)], PREFIX)
        self.assertIn("_agentview_boot", made[0])
        gone = [c for c in calls if "kill-session" in c]
        self.assertEqual(gone, [["tmux", "kill-session", "-t", "=_agentview_boot"]])

    def test_a_server_that_is_already_there_is_left_alone(self):
        calls = []
        with mock.patch.object(snapshot, "_run", side_effect=lambda a, timeout=4: calls.append(a) or ok()):
            snapshot._wait_tmux_settled(max_wait=0)
        self.assertFalse([c for c in calls if "new-session" in c])


class Restoring(Scoped):
    """`restore` with every leaf faked: what it hands to the shell."""

    def run_restore(self, snap):
        calls = []

        def run(argv, timeout=4):
            calls.append(argv)
            return ok(returncode=1) if argv[:2] == ["tmux", "has-session"] else ok()

        patches = [
            mock.patch.object(snapshot, "_run", side_effect=run),
            mock.patch.object(snapshot, "live_peers", return_value=[]),
            mock.patch.object(snapshot, "tmux_clients", return_value=[]),
            mock.patch.object(snapshot, "tmux_panes", return_value=[]),
            mock.patch.object(snapshot, "wez_panes", side_effect=lambda: self.panes),
            mock.patch.object(snapshot, "_gui_running", side_effect=self.gui),
            mock.patch.object(snapshot, "_wait_tmux_settled"),
            mock.patch.object(snapshot, "seed_name"),
            mock.patch.object(snapshot, "wait_named", return_value="x"),
            mock.patch.object(snapshot.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        snapshot.restore(snap, log=lambda *_: None)
        return calls

    REC = {"sessionId": "s1", "name": "Ada", "cwd": "/tmp", "flags": ""}

    panes = []          # what `wezterm cli list` says; a test that starts a window fills it

    def gui(self):
        """No window at first; one as soon as `wezterm start` has been run."""
        return self.started.called if hasattr(self, "started") else False

    def test_a_conversation_with_no_place_gets_a_tmux_session_in_its_own_scope(self):
        calls = self.run_restore({"sessions": [self.REC], "tmux": [], "wezterm": []})
        made = [c for c in calls if "new-session" in c]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0][:len(PREFIX)], PREFIX)
        self.assertIn("claude --resume s1", made[0])

    def test_a_tmux_session_from_the_snapshot_is_created_in_its_own_scope(self):
        snap = {"sessions": [{**self.REC, "tmux": {"session": "w", "window": 0, "pane": 0}}],
                "tmux": [{"name": "w", "windows": [{"index": 0, "layout": "L", "panes": [
                    {"index": 0, "cwd": "/tmp", "sessionId": "s1"}]}]}], "wezterm": []}
        calls = self.run_restore(snap)
        made = [c for c in calls if "new-session" in c]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0][:len(PREFIX)], PREFIX)
        # Everything after it talks to a server that is running.
        for c in calls:
            if c is not made[0] and c[0] == "tmux":
                self.assertNotEqual(c[:len(PREFIX)], PREFIX, c)

    def test_a_window_the_restore_has_to_start_is_scoped_and_a_tab_in_one_is_not(self):
        snap = {"sessions": [self.REC], "tmux": [],
                "wezterm": [{"tabs": [{"kind": "claude", "sessionId": "s1"}]}]}
        popen = self.started = mock.Mock()
        self.panes = [{"window_id": 1, "tty": "", "pane_id": 1}]
        with mock.patch.object(snapshot.subprocess, "Popen", popen):
            self.run_restore(snap)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:len(PREFIX)], PREFIX)
        self.assertEqual(argv[len(PREFIX) + 2:][:2], ["wezterm", "start"])


class Windows(Scoped):
    def test_a_window_started_by_the_closed_list_is_scoped(self):
        popen = mock.Mock()
        with mock.patch.object(jump, "_pid_of_command", return_value=None), \
                mock.patch.object(jump.subprocess, "Popen", popen):
            done = jump.open_tab(["claude", "--resume", "s1"], cwd="/tmp")
        self.assertTrue(done["ok"])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:len(PREFIX)], PREFIX)
        self.assertEqual(argv[len(PREFIX) + 2:],
                         ["wezterm", "start", "--cwd", "/tmp", "--", "claude", "--resume", "s1"])

    def test_a_tab_in_the_window_that_is_there_is_asked_for_not_started(self):
        ran = []

        def run(argv, timeout=4):
            ran.append(argv)
            return ok(stdout='[{"window_id": 3}]' if "list" in argv else "7")

        with mock.patch.object(jump, "_pid_of_command", return_value=123), \
                mock.patch.object(jump, "_run", side_effect=run), \
                mock.patch.object(jump, "_raise"):
            done = jump.open_tab(["claude"], cwd="/tmp")
        self.assertTrue(done["ok"])
        spawn = [a for a in ran if "spawn" in a]
        self.assertEqual(len(spawn), 1)
        self.assertEqual(spawn[0][0], "wezterm")
        self.assertNotIn("systemd-run", spawn[0])

    def test_with_no_user_manager_the_window_still_opens(self):
        popen = mock.Mock()
        with mock.patch.object(scope, "why_not", return_value="systemd-run exited 1: no bus"), \
                mock.patch.object(jump, "_pid_of_command", return_value=None), \
                mock.patch.object(jump.subprocess, "Popen", popen):
            done = jump.open_tab(["claude"], cwd="/tmp")
        self.assertTrue(done["ok"])
        self.assertEqual(popen.call_args.args[0][:2], ["wezterm", "start"])


if __name__ == "__main__":
    unittest.main()
