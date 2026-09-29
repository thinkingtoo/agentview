"""The decisions in scripts/scope-check: what it may touch, and what counts as a pass.

`scope-check` starts things in a transient unit of the real user manager, so
the parts that keep it away from the owner's tmux and WezTerm are pinned here
with fakes only: no systemd, no tmux, no WezTerm. What the real run shows is
in the ticket.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scope-check"


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
        self.assertTrue(env["PATH"].startswith(f"{self.box}/bin:"))
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "TMUX_TMPDIR", "CLAUDE_CONFIG_DIR"):
            self.assertTrue(env[key].startswith(str(self.box)), key)
        self.assertEqual(env["AVSC_RUN"], "abcd1234")

    def test_the_control_turns_scoping_off_and_the_scoped_run_does_not(self):
        self.assertEqual(sc.env_for(self.box, "off", "r")["AGENTVIEW_SCOPE"], "off")
        self.assertNotIn(sc.env_for(self.box, "on", "r")["AGENTVIEW_SCOPE"].lower(), ("off", "0", "no", "false"))


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

    def row(self, role, cgroup=None, scope="run-u1.scope", oom="continue"):
        return {"role": role, "pid": 1, "start": "1", "desc": "", "scope": scope, "oom": oom,
                "cgroup": cgroup or f"/user.slice/user@1000.service/app.slice/{scope}"}

    def rows(self, **inside):
        """One row per role; a role named in `inside` sits in the unit's cgroup."""
        out = []
        for role in sc.SCOPED + (sc.PANE,):
            out.append(self.row(role, cgroup=self.CG, scope="", oom="") if role in inside else self.row(role))
        return out

    def alive(self, **kw):
        return {role: kw.get(role, True) for role in sc.SCOPED + (sc.PANE,)}

    def test_scoped_run_where_everything_is_in_a_scope_and_survives_is_clean(self):
        self.assertEqual(sc.judge("on", self.rows(), self.CG, self.alive()), [])

    def test_scoped_run_fails_for_a_process_left_in_the_units_cgroup(self):
        problems = sc.judge("on", self.rows(**{"tmux server": 1}), self.CG, self.alive())
        self.assertTrue(any(p.startswith("tmux server: not in a scope") for p in problems), problems)

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

    def test_control_loses_what_was_in_the_units_cgroup(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        self.assertEqual(sc.judge("off", rows, self.CG, self.alive(**{r: False for r in sc.SCOPED})), [])

    def test_control_that_keeps_something_is_a_failure(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        problems = sc.judge("off", rows, self.CG, self.alive())
        self.assertEqual(len(problems), len(sc.SCOPED), problems)
        self.assertTrue(all("survived the restart with no scope" in p for p in problems))

    def test_control_that_never_had_anything_in_the_cgroup_proves_nothing(self):
        problems = sc.judge("off", self.rows(), self.CG, self.alive(**{r: False for r in sc.SCOPED}))
        self.assertTrue(all("proves nothing" in p for p in problems) and len(problems) == len(sc.SCOPED), problems)

    def test_the_pane_is_reported_in_the_control_but_not_judged(self):
        rows = self.rows(**{r: 1 for r in sc.SCOPED})
        alive = self.alive(**{r: False for r in sc.SCOPED})
        self.assertEqual(sc.judge("off", rows, self.CG, {**alive, sc.PANE: True}), [])
        self.assertEqual(sc.judge("off", rows, self.CG, {**alive, sc.PANE: False}), [])


class Identity(unittest.TestCase):
    """A unit is only restarted or stopped while it is still the one this run made."""

    def unit(self):
        unit = sc.Unit("abcd1234", "on")
        unit.inv = "inv-1"
        return unit

    def test_it_is_this_run_when_description_and_invocation_match(self):
        with mock.patch.object(sc, "show", return_value={"Description": "scope-check abcd1234 on", "InvocationID": "inv-1"}):
            self.assertTrue(self.unit().mine())

    def test_it_is_not_when_the_description_is_someone_elses(self):
        with mock.patch.object(sc, "show", return_value={"Description": "agentview — local dashboard", "InvocationID": "inv-1"}):
            self.assertFalse(self.unit().mine())

    def test_it_is_not_when_the_invocation_changed(self):
        with mock.patch.object(sc, "show", return_value={"Description": "scope-check abcd1234 on", "InvocationID": "inv-2"}):
            self.assertFalse(self.unit().mine())

    def test_a_unit_that_does_not_exist_is_not_this_run(self):
        with mock.patch.object(sc, "show", return_value={"Description": "", "InvocationID": ""}):
            self.assertFalse(self.unit().mine())

    def test_stop_and_restart_do_nothing_to_a_unit_that_is_not_this_run(self):
        with mock.patch.object(sc, "show", return_value={"Description": "x", "InvocationID": "inv-1"}), \
                mock.patch.object(sc, "ctl", side_effect=AssertionError("systemctl must not be called")):
            self.unit().stop()
            with self.assertRaises(sc.Abort):
                self.unit().restart()

    def test_every_unit_name_carries_the_run_id_and_never_names_the_service(self):
        for mode in ("on", "off"):
            name = sc.Unit("abcd1234", mode).name
            self.assertTrue(name.startswith("avsc-abcd1234-"))
            self.assertNotIn("agentview", name)


if __name__ == "__main__":
    unittest.main()
