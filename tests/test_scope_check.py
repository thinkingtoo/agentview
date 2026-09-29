"""The decisions in scripts/scope-check: what it may touch, and what counts as a pass.

`scope-check` starts things in a transient unit of the real user manager, so
the parts that keep it away from the owner's tmux and WezTerm, and the parts
that decide what it may stop, are pinned here with fakes only: no systemd, no
tmux, no WezTerm. What the real run shows is in the ticket.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "scope-check"
sys.path.insert(0, str(REPO))


def load():
    loader = importlib.machinery.SourceFileLoader("scope_check", str(SCRIPT))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("scope_check", loader))
    loader.exec_module(module)
    return module


sc = load()


def script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def done(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Box(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.box = self.tmp / "box"


class Shims(Box):
    def test_tmux_is_the_real_binary_with_no_config_a_private_socket_and_no_TMUX(self):
        real = script(self.tmp / "real-tmux", 'echo "$@"\necho "TMUX=${TMUX-unset}"\n')
        body = sc.fakes(self.box, str(real))["tmux"]
        shim = script(self.tmp / "tmux", body.split("\n", 1)[1])
        out = subprocess.run([str(shim), "list-sessions"], capture_output=True, text=True,
                             env={"PATH": "/usr/bin:/bin", "TMUX": "/tmp/tmux-1000/default,1,0"}).stdout
        self.assertEqual(out.splitlines(), [f"-f /dev/null -S {self.box}/t.sock list-sessions", "TMUX=unset"])

    def test_wezterm_logs_a_start_and_does_nothing_for_anything_else(self):
        script(self.tmp / "bin" / "sleep", "exit 0\n")           # the window's `sleep 3600`
        shim = script(self.tmp / "wezterm", "")
        shim.write_text(sc.fakes(self.box, "/bin/true")["wezterm"])
        self.box.mkdir()
        env = {"PATH": f"{self.tmp}/bin:/usr/bin:/bin"}
        for argv in (["cli", "list"], ["cli", "spawn", "--", "claude"], []):
            self.assertEqual(subprocess.run([str(shim)] + argv, env=env).returncode, 0)
        self.assertFalse((self.box / "windows").exists())
        subprocess.run([str(shim), "start", "--cwd", "/x", "--", "claude", "--resume", "w9"], env=env)
        line = (self.box / "windows").read_text().split()
        self.assertEqual(line[1:], ["start", "--cwd", "/x", "--", "claude", "--resume", "w9"])
        self.assertTrue(line[0].isdigit())


class Environment(Box):
    def test_nothing_of_the_callers_desktop_or_terminal_reaches_the_unit(self):
        hostile = {"TMUX": "/tmp/tmux-1000/default,1,0", "WEZTERM_PANE": "3", "WEZTERM_UNIX_SOCKET": "/x",
                   "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "SSH_AUTH_SOCK": "/s", "HOME": "/home/real",
                   "XDG_RUNTIME_DIR": "/run/user/1000", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        with mock.patch.dict(os.environ, hostile):
            env = sc.env_for(self.box, "on", "abcd1234")
        self.assertEqual(sorted(env), sorted(["PATH", "HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
                                              "TMUX_TMPDIR", "CLAUDE_CONFIG_DIR", "AVSC_RUN", "AGENTVIEW_SCOPE",
                                              "DBUS_SESSION_BUS_ADDRESS"]))
        self.assertEqual(env["PATH"], f"{self.box}/bin")          # nothing else: no real tmux, wezterm or claude
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "TMUX_TMPDIR", "CLAUDE_CONFIG_DIR"):
            self.assertTrue(env[key].startswith(str(self.box)), key)
        self.assertEqual(env["AVSC_RUN"], "abcd1234")

    def test_the_control_turns_scoping_off_and_the_scoped_run_does_not(self):
        self.assertEqual(sc.env_for(self.box, "off", "r")["AGENTVIEW_SCOPE"], "off")
        self.assertNotIn(sc.env_for(self.box, "on", "r")["AGENTVIEW_SCOPE"].lower(), ("off", "0", "no", "false"))

    def test_the_unit_runs_the_driver_in_that_environment_and_no_other(self):
        cmd = sc.driver_command(self.box, "on", "abcd1234")
        self.assertEqual(cmd[:2], ["/usr/bin/env", "-i"])
        pairs = [f"{k}={v}" for k, v in sc.env_for(self.box, "on", "abcd1234").items()]
        self.assertEqual(cmd[2:2 + len(pairs)], pairs)
        self.assertEqual(cmd[2 + len(pairs):], [sys.executable, str(SCRIPT.resolve()), "--driver", str(self.box), "on"])

    @unittest.skipUnless(all(shutil.which(t) for t in sc.TOOLS), "needs systemd-run, systemctl, sleep and true")
    def test_the_box_holds_the_shims_and_four_links_and_nothing_else(self):
        sc.fill_box(self.box, "/usr/bin/tmux")
        self.assertEqual(sorted(p.name for p in (self.box / "bin").iterdir()),
                         sorted(["tmux", "wezterm", "pgrep", "claude", *sc.TOOLS]))
        for tool in sc.TOOLS:
            link = self.box / "bin" / tool
            self.assertTrue(link.is_symlink() and os.path.isabs(os.readlink(link)), tool)

    def test_a_socket_path_too_long_for_a_unix_socket_aborts(self):
        with self.assertRaises(sc.Abort):
            sc.check_socket_path(self.tmp / ("x" * 100))
        sc.check_socket_path(self.box)


class Preflight(Box):
    """`tmux` in the box answers as a fake; what matters is when the check aborts."""

    def box_with(self, body):
        script(self.box / "bin" / "tmux", body)
        return {"PATH": f"{self.box}/bin:/usr/bin:/bin"}

    def test_it_passes_when_tmux_names_the_private_socket_and_has_no_server_there(self):
        env = self.box_with(f'echo "error connecting to {self.box}/t.sock (No such file or directory)" >&2\nexit 1\n')
        sc.preflight(self.box, env)

    def test_it_aborts_when_tmux_names_another_socket(self):
        env = self.box_with('echo "error connecting to /tmp/tmux-1000/default (No such file or directory)" >&2\nexit 1\n')
        with self.assertRaises(sc.Abort):
            sc.preflight(self.box, env)

    def test_it_aborts_when_a_server_answers_on_the_private_socket(self):
        env = self.box_with(f'echo "0: 1 windows" \necho "{self.box}/t.sock" >&2\nexit 0\n')
        with self.assertRaises(sc.Abort):
            sc.preflight(self.box, env)

    def test_it_aborts_when_tmux_is_not_the_shim(self):
        self.box_with("exit 1\n")
        other = script(self.tmp / "elsewhere" / "tmux", "exit 1\n").parent
        with self.assertRaises(sc.Abort) as raised:
            sc.preflight(self.box, {"PATH": f"{other}:{self.box}/bin:/usr/bin:/bin"})
        self.assertIn("not the shim", str(raised.exception))


class ProbingAScope(Box):
    """Inside a scope, wezterm and tmux must still be the shims."""

    def probe(self, result):
        wrapped = ["a-scope", "wrapping", "sh"]
        with mock.patch("scope.wrap", return_value=wrapped) as wrap, \
                mock.patch.object(sc.subprocess, "run", return_value=result) as run:
            sc.probe_scope(self.box, "r1")
        self.assertEqual(run.call_args.args[0], wrapped)
        self.assertEqual(wrap.call_args.args[0][:2], ["/bin/sh", "-c"])

    def shims(self, *extra):
        return "\n".join([f"{self.box}/bin/wezterm", f"{self.box}/bin/tmux", *extra])

    def test_it_passes_when_the_scope_finds_the_shims_and_carries_the_marker(self):
        self.probe(done(stdout=self.shims("r1")))

    def test_it_aborts_when_the_scope_finds_a_real_wezterm(self):
        with self.assertRaises(sc.Abort):
            self.probe(done(stdout="/usr/bin/wezterm\n" + f"{self.box}/bin/tmux\nr1"))

    def test_it_aborts_when_the_scope_finds_nothing_or_loses_the_marker_or_fails(self):
        for result in (done(stdout="\n\nr1"), done(stdout=self.shims("other")), done(1, self.shims("r1"))):
            with self.assertRaises(sc.Abort):
                self.probe(result)


class Reading(unittest.TestCase):
    def test_a_process_name_with_spaces_and_parentheses_does_not_shift_the_fields(self):
        after = ["S"] + [str(n) for n in range(1, 19)] + ["987654"] + ["0"] * 5
        self.assertEqual(sc.parse_stat("123 (a b) c) " + " ".join(after)), ("S", "987654"))

    def test_marked_finds_a_process_by_its_run_and_only_by_its_run(self):
        proc = subprocess.Popen(["sleep", "30"], env={"PATH": "/usr/bin:/bin", "AVSC_RUN": "unit-test-run"})
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertIn(proc.pid, sc.marked("unit-test-run"))
        self.assertNotIn(proc.pid, sc.marked("unit-test-run-2"))
        self.assertNotIn(proc.pid, sc.marked("unit-test"))


class Judging(unittest.TestCase):
    CG = "/user.slice/user@1000.service/app.slice/avsc-x-on.service"

    def row(self, role, cgroup=None, scope="run-u1.scope", oom="continue", desc="agentview: a scope"):
        return {"role": role, "pid": 1, "start": "1", "desc": desc, "scope": scope, "oom": oom,
                "cgroup": cgroup or f"/user.slice/user@1000.service/app.slice/{scope}"}

    def rows(self, **inside):
        """One row per role; a role named in `inside` sits in the unit's cgroup."""
        return [self.row(role, cgroup=self.CG, scope="", oom="", desc="") if role in inside else self.row(role)
                for role in sc.SCOPED + (sc.PANE,)]

    def alive(self, **kw):
        return {role: kw.get(role, True) for role in sc.SCOPED + (sc.PANE,)}

    def test_scoped_run_where_everything_is_in_a_scope_and_survives_is_clean(self):
        self.assertEqual(sc.judge("on", self.rows(), self.CG, self.alive()), [])

    def test_scoped_run_fails_for_a_process_left_in_the_units_cgroup(self):
        problems = sc.judge("on", self.rows(**{"tmux server": 1}), self.CG, self.alive())
        self.assertTrue(any(p.startswith("tmux server: not in a scope") for p in problems), problems)

    def test_scoped_run_fails_for_a_scope_that_scope_wrap_did_not_make(self):
        rows = self.rows()
        rows[0]["desc"] = "tmux child pane %0 of terminal /dev/pts/1"
        self.assertTrue(any("not in a scope that scope.wrap made" in p for p in sc.judge("on", rows, self.CG, self.alive())))

    def test_scoped_run_fails_for_a_scope_that_stops_on_an_oom_kill(self):
        rows = self.rows()
        rows[0]["oom"] = "stop"
        self.assertTrue(any("OOMPolicy" in p for p in sc.judge("on", rows, self.CG, self.alive())))

    def test_scoped_run_fails_for_a_session_that_did_not_survive(self):
        problems = sc.judge("on", self.rows(), self.CG, self.alive(**{sc.PANE: False}))
        self.assertEqual(problems, [f"{sc.PANE}: gone after the restart"])

    def test_a_missing_record_is_a_failure_not_a_pass(self):
        problems = sc.judge("on", self.rows()[:-1], self.CG, self.alive())
        self.assertIn(f"{sc.PANE}: not recorded", problems)

    def test_control_loses_what_was_in_the_units_cgroup_and_the_pane(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        gone = self.alive(**{r: False for r in sc.SCOPED + (sc.PANE,)})
        self.assertEqual(sc.judge("off", rows, self.CG, gone), [])

    def test_control_that_keeps_a_process_is_a_failure(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        problems = sc.judge("off", rows, self.CG, self.alive(**{sc.PANE: False}))
        self.assertEqual(len(problems), len(sc.SCOPED), problems)
        self.assertTrue(all("survived the restart with no scope" in p for p in problems))

    def test_control_that_keeps_its_pane_is_a_failure(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        problems = sc.judge("off", rows, self.CG, self.alive(**{r: False for r in sc.SCOPED}))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith(f"{sc.PANE}: outlived its tmux server"), problems)

    def test_control_that_never_had_anything_in_the_cgroup_proves_nothing(self):
        gone = self.alive(**{r: False for r in sc.SCOPED + (sc.PANE,)})
        problems = sc.judge("off", self.rows(), self.CG, gone)
        self.assertTrue(all("proves nothing" in p for p in problems) and len(problems) == len(sc.SCOPED), problems)


class Identity(unittest.TestCase):
    """A unit is only restarted or stopped once its start was attempted, and while it is still that one."""

    DESC = "scope-check abcd1234 on"

    def unit(self, attempted=True, inv="inv-1"):
        unit = sc.Unit("abcd1234", "on")
        unit.attempted, unit.inv = attempted, inv
        return unit

    def test_it_is_this_run_when_description_and_invocation_match(self):
        with mock.patch.object(sc, "show", return_value={"Description": self.DESC, "InvocationID": "inv-1"}):
            self.assertTrue(self.unit().mine())

    def test_it_is_not_when_the_description_is_someone_elses(self):
        with mock.patch.object(sc, "show", return_value={"Description": "agentview — local dashboard", "InvocationID": "inv-1"}):
            self.assertFalse(self.unit().mine())

    def test_it_is_not_when_the_invocation_changed(self):
        with mock.patch.object(sc, "show", return_value={"Description": self.DESC, "InvocationID": "inv-2"}):
            self.assertFalse(self.unit().mine())

    def test_a_unit_that_does_not_exist_is_not_this_run(self):
        with mock.patch.object(sc, "show", return_value={"Description": "", "InvocationID": ""}):
            self.assertFalse(self.unit().mine())

    def test_a_unit_whose_start_was_never_attempted_is_not_this_run_whatever_it_says(self):
        with mock.patch.object(sc, "show", return_value={"Description": self.DESC, "InvocationID": ""}), \
                mock.patch.object(sc, "ctl") as ctl:
            unit = self.unit(attempted=False, inv="")
            self.assertFalse(unit.mine())
            unit.stop()
        ctl.assert_not_called()

    def test_stop_and_restart_do_nothing_to_a_unit_that_is_not_this_run(self):
        with mock.patch.object(sc, "show", return_value={"Description": "x", "InvocationID": "inv-1"}), \
                mock.patch.object(sc, "ctl") as ctl:
            self.unit().stop()
            with self.assertRaises(sc.Abort):
                self.unit().restart()
        ctl.assert_not_called()

    def test_a_failed_systemd_run_is_never_followed_by_a_stop_of_that_name(self):
        unit = sc.Unit("abcd1234", "on")
        with mock.patch.object(sc.subprocess, "run", return_value=done(1, stderr="Unit already exists")), \
                mock.patch.object(sc, "show", return_value={"Description": "someone else's", "InvocationID": "x"}), \
                mock.patch.object(sc, "ctl") as ctl:
            with self.assertRaises(sc.Abort):
                unit.start(["true"])
            unit.stop()
        ctl.assert_not_called()

    def test_a_start_with_no_invocation_id_can_still_be_stopped_because_it_was_ours(self):
        unit = sc.Unit("abcd1234", "on")
        with mock.patch.object(sc.subprocess, "run", return_value=done()), \
                mock.patch.object(sc, "show", return_value={"Description": self.DESC, "InvocationID": ""}), \
                mock.patch.object(sc, "ctl") as ctl:
            with self.assertRaises(sc.Abort):
                unit.start(["true"])
            unit.stop()
        self.assertEqual([c.args[0] for c in ctl.call_args_list], ["stop", "reset-failed"])

    def test_a_restart_that_failed_still_leaves_the_new_invocation_reachable_for_the_stop(self):
        unit = self.unit()
        states = iter([{"Description": self.DESC, "InvocationID": "inv-1"},                       # mine() before
                       {"Description": self.DESC, "ActiveState": "failed", "InvocationID": "inv-2"},   # after
                       {"Description": self.DESC, "InvocationID": "inv-2"}])                      # mine() in stop()
        with mock.patch.object(sc, "show", side_effect=lambda *a: next(states)), \
                mock.patch.object(sc, "ctl", return_value=done(1)) as ctl:
            with self.assertRaises(sc.Abort):
                unit.restart()
            self.assertEqual(unit.inv, "inv-2")
            unit.stop()
        self.assertEqual([c.args[0] for c in ctl.call_args_list], ["restart", "stop", "reset-failed"])

    def test_every_unit_name_carries_the_run_id_and_never_names_the_service(self):
        for mode in ("on", "off"):
            name = sc.Unit("abcd1234", mode).name
            self.assertTrue(name.startswith("avsc-abcd1234-"))
            self.assertNotIn("agentview", name)


class Ownership(Box):
    """What `exercise` may touch when it fails early."""

    def run_exercise(self, run, systemd_run=None):
        """exercise() in a temporary runtime directory; every way out to the
        machine is a recording mock. `systemd_run` is what the first
        subprocess call, the start of the unit, returns."""
        calls = SimpleNamespace(run=mock.Mock(side_effect=[systemd_run or done()] + [done()] * 5),
                                ctl=mock.Mock(return_value=done()),
                                show=mock.Mock(return_value={"Description": "", "InvocationID": ""}))
        with mock.patch.object(sc, "RUNTIME", self.tmp), \
                mock.patch.object(sc.subprocess, "run", calls.run), \
                mock.patch.object(sc, "ctl", calls.ctl), mock.patch.object(sc, "show", calls.show), \
                mock.patch.object(sc, "fill_box", side_effect=lambda box, real: (box / "bin").mkdir()), \
                mock.patch.object(sc, "preflight"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = sc.exercise(run, "on", "/real/tmux")
        return code, calls, out.getvalue()

    def test_a_box_that_already_exists_is_left_alone_and_nothing_is_run(self):
        existing = self.tmp / "avsc-r1-on"
        existing.mkdir()
        (existing / "t.sock").write_text("someone else's")
        code, calls, out = self.run_exercise("r1")
        self.assertEqual(code, 2)
        self.assertIn("ABORTED", out)
        calls.run.assert_not_called()
        calls.ctl.assert_not_called()
        self.assertEqual((existing / "t.sock").read_text(), "someone else's")

    def test_when_systemd_run_fails_no_unit_is_stopped_but_this_runs_private_server_is_killed(self):
        code, calls, _ = self.run_exercise("r2", systemd_run=done(1, stderr="Unit already exists"))
        self.assertEqual(code, 2)
        self.assertNotIn("stop", [c.args[0] for c in calls.ctl.call_args_list])
        made = [c.args[0] for c in calls.run.call_args_list]
        self.assertEqual(made[0][:3], ["systemd-run", "--user", "--quiet"])
        self.assertEqual(made[1:], [["/real/tmux", "-f", "/dev/null", "-S", f"{self.tmp}/avsc-r2-on/t.sock", "kill-server"]])
        self.assertFalse((self.tmp / "avsc-r2-on").exists())

    def test_a_failed_cleanup_step_does_not_skip_the_ones_after_it(self):
        with mock.patch.object(sc.Unit, "start", side_effect=sc.Abort("boom")), \
                mock.patch.object(sc.Unit, "stop", side_effect=RuntimeError("no bus")), \
                mock.patch.object(sc, "our_scopes", return_value=["run-u9.scope"]):
            code, calls, out = self.run_exercise("r3")
        self.assertEqual(code, 2)
        self.assertIn("cleanup step failed: RuntimeError", out)
        self.assertEqual(len(calls.run.call_args_list), 1)                       # kill-server still ran
        self.assertEqual([c.args for c in calls.ctl.call_args_list], [("stop", "run-u9.scope")])

    def test_a_marked_process_that_survives_keeps_the_box_and_makes_the_run_exit_2(self):
        with mock.patch.object(sc.Unit, "start", side_effect=sc.Abort("boom")), \
                mock.patch.object(sc, "marked", return_value={4242}), \
                mock.patch.object(sc, "our_scopes", return_value=[]), \
                mock.patch.object(sc.time, "sleep"), \
                mock.patch.object(sc.time, "time", side_effect=itertools.chain([0, 0], itertools.repeat(20))):
            code, _, out = self.run_exercise("r4")
        self.assertEqual(code, 2)
        self.assertIn("LEFT BEHIND", out)
        self.assertIn("4242", out)
        self.assertTrue((self.tmp / "avsc-r4-on").exists())


    def test_signals_are_held_while_cleaning_up_and_given_back_after(self):
        seen = []
        with mock.patch.object(sc.signal, "signal", side_effect=lambda s, h: seen.append((s, h)) or f"old-{s}"), \
                mock.patch.object(sc.Unit, "start", side_effect=sc.Abort("boom")):
            self.run_exercise("r5")
        self.assertEqual(seen, [(sc.signal.SIGINT, sc.signal.SIG_IGN), (sc.signal.SIGTERM, sc.signal.SIG_IGN),
                                (sc.signal.SIGINT, f"old-{sc.signal.SIGINT}"),
                                (sc.signal.SIGTERM, f"old-{sc.signal.SIGTERM}")])


class Driving(Box):
    """The driver launches nothing until both preflights have passed, and the
    restarted unit's second copy launches nothing at all."""

    def setUp(self):
        super().setUp()
        import jump
        import snapshot
        self.box.mkdir()
        self.order = []
        record = self.recording
        patches = [
            mock.patch.dict(os.environ, {"AVSC_RUN": "r9"}),
            mock.patch.object(sc, "preflight", record("preflight")),
            mock.patch.object(sc, "probe_scope", record("probe_scope")),
            mock.patch.object(sc, "window_pid", side_effect=[111, 222]),
            mock.patch.object(sc, "describe", side_effect=lambda role, pid: {"role": role, "pid": pid}),
            mock.patch.object(sc, "idle", side_effect=SystemExit),
            mock.patch.object(jump, "open_tab", record("open_tab", {"ok": True})),
            mock.patch.object(snapshot, "_start_gui", record("_start_gui", 1)),
            mock.patch.object(snapshot, "_run", side_effect=lambda argv, **k: self.order.append(argv[:2]) or done(stdout="123")),
            mock.patch("scope.why_not", return_value="AGENTVIEW_SCOPE is off"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def recording(self, name, ret=None):
        """A stand-in that notes when it was called and returns `ret`."""
        def call(*_args, **_kwargs):
            self.order.append(name)
            return ret
        return mock.Mock(side_effect=call)

    def aborting(self, name):
        def call(*_args):
            self.order.append(name)
            raise sc.Abort("no")
        return call

    def test_it_runs_both_preflights_first_and_then_starts_through_the_real_helpers(self):
        with self.assertRaises(SystemExit):
            sc.driver(self.box, "on")
        self.assertEqual(self.order, ["preflight", "probe_scope", "open_tab", "_start_gui", ["tmux", "new-session"],
                                      ["tmux", "display-message"], ["tmux", "list-panes"]])
        self.assertEqual([r["role"] for r in json.loads((self.box / "record.json").read_text())],
                         ["window via jump.open_tab", "window via snapshot._start_gui", "tmux server", "tmux pane"])
        self.assertTrue((self.box / "ready").exists())

    def test_it_launches_nothing_when_either_preflight_aborts(self):
        for name in ("preflight", "probe_scope"):
            self.order.clear()
            (self.box / "started").unlink(missing_ok=True)
            with mock.patch.object(sc, name, side_effect=self.aborting(name)):
                with self.assertRaises(sc.Abort):
                    sc.driver(self.box, "on")
            self.assertNotIn("open_tab", self.order)
            self.assertNotIn("_start_gui", self.order)
            self.assertFalse([o for o in self.order if isinstance(o, list)], self.order)

    def test_the_second_copy_after_a_restart_launches_and_checks_nothing(self):
        (self.box / "started").write_text("")
        with self.assertRaises(SystemExit):
            sc.driver(self.box, "on")
        self.assertEqual(self.order, [])


class Desktop(unittest.TestCase):
    def listing(self, tmux, wezterm):
        """`desktop()` with the two real listings replaced by these results."""
        def run(argv, **kw):
            return tmux if argv[0] == "/usr/bin/tmux" else wezterm
        with mock.patch.object(sc.subprocess, "run", side_effect=run):
            return sc.desktop("/usr/bin/tmux")

    WEZ = done(stdout='[{"window_id": 0, "tab_id": 0, "pane_id": 0}, {"window_id": 0, "tab_id": 1, "pane_id": 1}]')

    def test_a_listing_that_worked_is_a_sorted_list(self):
        got = self.listing(done(stdout="$3 b\n$2 a\n"), self.WEZ)
        self.assertEqual(got, {"tmux sessions": ["$2 a", "$3 b"], "wezterm windows and tabs": [(0, 0), (0, 1)]})

    def test_a_tmux_with_no_server_is_an_empty_list_and_any_other_failure_is_not_a_list(self):
        self.assertEqual(self.listing(done(1, stderr="no server running on /tmp/tmux-1000/default"), self.WEZ)["tmux sessions"], [])
        self.assertIsNone(self.listing(done(1, stderr="protocol version mismatch"), self.WEZ)["tmux sessions"])

    def test_a_wezterm_that_cannot_be_listed_is_none(self):
        for bad in (done(1, stderr="no gui"), done(stdout="not json")):
            self.assertIsNone(self.listing(done(), bad)["wezterm windows and tabs"])

    def compare(self, before, after):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            return sc.compare(before, after, "r1"), out.getvalue()

    def test_identical_listings_are_exit_0(self):
        same = {"tmux sessions": ["$2 a"], "wezterm windows and tabs": [(0, 0)]}
        code, out = self.compare(same, dict(same))
        self.assertEqual(code, 0)
        self.assertIn("exactly as before", out)

    def test_a_listing_that_failed_on_both_sides_is_not_unchanged(self):
        both = {"tmux sessions": ["$2 a"], "wezterm windows and tabs": None}
        code, out = self.compare(both, dict(both))
        self.assertEqual(code, 3)
        self.assertIn("could not be listed", out)
        self.assertNotIn("exactly as before", out)

    def test_a_difference_is_exit_3_and_says_whether_it_carries_this_runs_name(self):
        before = {"tmux sessions": ["$2 a"], "wezterm windows and tabs": [(0, 0)]}
        other = {"tmux sessions": ["$2 a", "$9 someone"], "wezterm windows and tabs": [(0, 0)]}
        code, out = self.compare(before, other)
        self.assertEqual(code, 3)
        self.assertIn("new ['$9 someone']", out)
        self.assertIn("none of the sessions carries this run's name (avsc-r1)", out)
        ours = {"tmux sessions": ["$2 a", "$9 avsc-r1"], "wezterm windows and tabs": [(0, 0)]}
        self.assertIn("sessions of this run on the real server: ['$9 avsc-r1']", self.compare(before, ours)[1])


class Main(unittest.TestCase):
    def main_with(self, exercises):
        same = {"tmux sessions": [], "wezterm windows and tabs": []}
        with mock.patch.object(sc, "exercise", side_effect=exercises) as ex, \
                mock.patch.object(sc, "desktop", return_value=same), \
                mock.patch.object(sc.shutil, "which", return_value="/usr/bin/tmux"), \
                mock.patch.object(sc.signal, "signal"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = sc.main()
        return code, ex, out.getvalue()

    def test_the_control_is_not_run_when_the_scoped_run_aborted_or_left_something(self):
        code, ex, out = self.main_with([2, AssertionError("the control must not run")])
        self.assertEqual(code, 2)
        self.assertEqual([c.args[1] for c in ex.call_args_list], ["on"])
        self.assertIn("control: not run", out)

    def test_both_runs_clean_and_the_desktop_unchanged_is_exit_0(self):
        code, ex, out = self.main_with([0, 0])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in ex.call_args_list], ["on", "off"])
        self.assertIn("PASS (exit 0)", out)

    def test_a_failed_expectation_in_the_scoped_run_still_runs_the_control(self):
        code, _, _ = self.main_with([1, 0])
        self.assertEqual(code, 1)

    def test_the_desktop_is_compared_even_when_a_run_is_interrupted(self):
        same = {"tmux sessions": [], "wezterm windows and tabs": []}
        with mock.patch.object(sc, "exercise", side_effect=KeyboardInterrupt), \
                mock.patch.object(sc, "desktop", return_value=same) as desktop, \
                mock.patch.object(sc.shutil, "which", return_value="/usr/bin/tmux"), \
                mock.patch.object(sc.signal, "signal"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(KeyboardInterrupt):
                sc.main()
        self.assertEqual(desktop.call_count, 2)
        self.assertIn("the real desktop", out.getvalue())


if __name__ == "__main__":
    unittest.main()
