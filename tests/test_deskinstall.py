"""The merge desk's Install items: found from the `uv tool` receipts, installed at the pinned commit, restarted after.

Everything runs against a throwaway folder: `UV_TOOL_DIR`, `XDG_STATE_HOME` and `XDG_RUNTIME_DIR` under it,
and `deskwatch.GH`, `deskinstall.EXES` set to fake `gh`, `uv` and `sheaf` scripts that write every call to one
`order.log`. The real receipts, the real sheaf hub and the real GitHub are never touched.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desk
import deskfile
import deskinstall
import deskwatch

OLD = "878d3e77407a348244713d8c87de7db4ed6cd171"
MID = "c" * 40
MAIN = "1a2b3c4" + "d" * 33
NEWER = "f" * 40
REPO = "sweatshop-ai/sheaf"
REAL_RECEIPT = f'''[tool]
requirements = [{{ name = "sheafmd", git = "https://github.com/sweatshop-ai/sheaf?rev={OLD}" }}]
entrypoints = [
    {{ name = "sheaf", install-path = "/home/tiroir/.local/bin/sheaf", from = "sheafmd" }},
]
'''

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_DIR"]
a = sys.argv[1:]
open(d + "/order.log", "a").write("gh " + " ".join(a[:2]) + "\\n")
if a[0] != "api":
    sys.exit(9)
if os.path.exists(d + "/gh-down"):
    print("HTTP 502", file=sys.stderr); sys.exit(1)
repo_file = d + "/history-" + a[1].split("/")[1] + "_" + a[1].split("/")[2] + ".txt"
hist = open(repo_file).read().split()
if a[1].endswith("/commits/main"):
    own = d + "/main-" + a[1].split("/")[1] + "_" + a[1].split("/")[2] + ".txt"
    print(open(own).read().strip() if os.path.exists(own) else hist[-1]); sys.exit(0)
base, head = a[1].split("/compare/")[1].split("...")
if base not in hist or head not in hist:
    print("Not Found", file=sys.stderr); sys.exit(1)
i, j = hist.index(base), hist.index(head)
print("identical 0" if i == j else f"ahead {{j - i}}" if j > i else f"behind {{i - j}}")
"""

FAKE_UV = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_DIR"]
a = sys.argv[1:]
open(d + "/order.log", "a").write("uv\\n")
open(d + "/uv.json", "a").write(json.dumps({{"argv": a, "path": os.environ.get("PATH")}}) + "\\n")
if os.path.exists(d + "/uv-fails"):
    print("error: Failed to build `sheafmd`", file=sys.stderr); sys.exit(1)
url = a[a.index("--from") + 1]
rev = url.split("@")[1]
pkg = a[-1]
f = os.environ["UV_TOOL_DIR"] + "/" + pkg + "/uv-receipt.toml"
old = open(f).read()
open(f, "w").write(old.split("rev=")[0] + "rev=" + rev + '" }}]\\nentrypoints = []\\n')
if os.path.exists(d + "/uv-kills-receipt"):
    os.remove(f)
"""

FAKE_SHEAF = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_DIR"]
cmd = sys.argv[1]
open(d + "/order.log", "a").write("sheaf " + cmd + "\\n")
open(d + "/sheaf.json", "a").write(json.dumps({{"cmd": cmd, "home": os.environ.get("SHEAF_HOME"),
                                                "port": os.environ.get("SHEAF_PORT")}}) + "\\n")
if cmd == "status":
    pid = open(d + "/hub.pid").read() if os.path.exists(d + "/hub.pid") else None
    if pid:
        print("  hub running on 127.0.0.1:27419\\n  pid      " + pid); sys.exit(0)
    sys.exit(1)
if os.path.exists(d + "/sheaf-" + cmd + "-fails"):
    print("sheaf: the hub refused to " + cmd, file=sys.stderr); sys.exit(1)
"""


def script(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def setUpModule():
    global _runtime
    _runtime = tempfile.mkdtemp()
    os.environ["XDG_RUNTIME_DIR"] = _runtime


def tearDownModule():
    os.environ.pop("XDG_RUNTIME_DIR", None)
    shutil.rmtree(_runtime, True)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.tools = self.tmp / "tools"
        env = {"XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_DIR": str(self.fake), "UV_TOOL_DIR": str(self.tools)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(lambda: [os.environ.pop(k) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        self.saved = (deskwatch.GH, deskwatch.sleep, deskwatch.log.error, deskwatch.GRACE, deskinstall.EXES, deskinstall.GRACE)
        self.errors = []
        deskwatch.GH = script(self.bin / "gh", FAKE_GH)
        deskwatch.GRACE = deskinstall.GRACE = 0
        deskwatch.sleep = lambda s: None
        deskwatch.log.error = lambda *a, **k: self.errors.append((a, k))
        deskwatch._warned.clear()
        deskinstall.EXES = {"uv": script(self.bin / "uv", FAKE_UV), "sheaf": script(self.bin / "sheaf", FAKE_SHEAF),
                            "systemd-run": None}
        self.addCleanup(self.restore)
        self.history([OLD, MID, MAIN])
        self.receipt("sheafmd", OLD)

    def restore(self):
        deskwatch.GH, deskwatch.sleep, deskwatch.log.error, deskwatch.GRACE, deskinstall.EXES, deskinstall.GRACE = self.saved

    def history(self, shas, repo=REPO):
        (self.fake / f"history-{repo.replace('/', '_')}.txt").write_text("\n".join(shas))

    def receipt(self, name, rev, text=None, folder=None):
        d = self.tools / (folder or name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "uv-receipt.toml").write_text(text if text is not None else REAL_RECEIPT.replace(OLD, rev))

    def rev(self, name="sheafmd"):
        return deskinstall.tool_named(name).rev

    def order(self):
        f = self.fake / "order.log"
        return f.read_text().split("\n")[:-1] if f.exists() else []

    def calls(self, name):
        f = self.fake / name
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def item(self, k="install:sheafmd"):
        return next((i for i in deskfile.items() if i.key == k), None)

    def tick_box(self, k="install:sheafmd"):
        deskfile.edit(lambda t: t.replace(f"- [ ] Install {k.removeprefix('install:')}:", f"- [x] Install {k.removeprefix('install:')}:"))

    def found(self):
        deskinstall.scan()
        return self.item()

    def events(self, k="install:sheafmd"):
        return [r["event"] for r in desk.history(k)]


class Receipts(Case):
    def test_the_real_receipt_is_read(self):
        got = deskinstall.read_receipt(self.tools / "sheafmd")
        self.assertEqual((got.name, got.package, got.repo, got.rev), ("sheafmd", "sheafmd", REPO, OLD))

    def test_tiroir_owner_is_known_too(self):
        self.receipt("x", OLD, REAL_RECEIPT.replace("sweatshop-ai/sheaf", "tiroir/thing.git"))
        self.assertEqual(deskinstall.tool_named("x").repo, "tiroir/thing")

    def test_odd_shapes_are_skipped(self):
        odd = {
            "path": '[tool]\nrequirements = [{ name = "a", path = "/x/a.whl" }]\n',
            "registry": '[tool]\nrequirements = [{ name = "a", specifier = ">=1" }]\n',
            "other owner": REAL_RECEIPT.replace("sweatshop-ai", "someone-else"),
            "other host": REAL_RECEIPT.replace("github.com", "gitlab.com"),
            "branch": REAL_RECEIPT.replace(f"rev={OLD}", "branch=main"),
            "no rev": REAL_RECEIPT.replace(f"?rev={OLD}", ""),
            "short rev": REAL_RECEIPT.replace(OLD, OLD[:12]),
            "two reqs": REAL_RECEIPT.replace("requirements = [", "requirements = [{ name = \"b\", specifier = \"*\" }, "),
            "dot-dot repo": REAL_RECEIPT.replace("sweatshop-ai/sheaf?", "sweatshop-ai/..?"),
            "extra key": REAL_RECEIPT.replace('name = "sheafmd",', 'name = "sheafmd", extras = ["x"],'),
            "subdirectory": REAL_RECEIPT.replace(OLD + '"', OLD + '#subdirectory=x"'),
            "name with a newline": REAL_RECEIPT.replace('name = "sheafmd"', 'name = "a\\nb"'),
            "not toml": "[[[",
            "empty": "",
            "no tool table": "x = 1\n",
            "requirements not a list": '[tool]\nrequirements = "x"\n',
        }
        for label, text in odd.items():
            with self.subTest(label):
                self.receipt("odd", OLD, text)
                self.assertIsNone(deskinstall.read_receipt(self.tools / "odd"))
        (self.tools / "norceipt").mkdir()
        (self.tools / "stray-file").write_text("x")
        self.assertEqual([t.name for t in deskinstall.receipts()], ["sheafmd"])

    def test_odd_receipts_never_become_items(self):
        self.receipt("odd", OLD, '[tool]\nrequirements = [{ name = "a", path = "/x/a.whl" }]\n')
        deskinstall.scan()
        self.assertEqual([i.key for i in deskfile.items()], ["install:sheafmd"])

    def test_the_tools_folder_follows_xdg_data_home(self):
        del os.environ["UV_TOOL_DIR"]
        self.addCleanup(os.environ.__setitem__, "UV_TOOL_DIR", str(self.tools))
        os.environ["XDG_DATA_HOME"] = str(self.tmp / "data")
        self.addCleanup(os.environ.pop, "XDG_DATA_HOME")
        self.assertEqual(deskinstall.tools_dir(), self.tmp / "data" / "uv" / "tools")


class Scan(Case):
    def test_a_tool_behind_main_is_one_item_with_both_commits(self):
        it = self.found()
        self.assertEqual((it.key, it.ticked, it.pinned), ("install:sheafmd", False, MAIN))
        self.assertIn(OLD, it.block)
        self.assertIn(MAIN, it.block)
        self.assertIn("2 commits behind main", it.block)
        text = deskfile.path().read_text()
        self.assertLess(text.index(deskfile.SECTIONS["install"]), text.index("- [ ] Install sheafmd"))
        self.assertEqual(len(deskfile.items()), 1)
        self.assertEqual(self.events(), ["ready"])

    def test_a_tool_at_main_has_none(self):
        self.receipt("sheafmd", MAIN)
        deskinstall.scan()
        self.assertEqual(deskfile.items(), [])

    def test_a_tool_ahead_of_or_diverged_from_main_has_none(self):
        self.history([OLD, MAIN])
        self.receipt("sheafmd", NEWER)
        deskinstall.scan()
        self.assertEqual(deskfile.items(), [])
        self.assertEqual([e[0][0] for e in self.errors], ["desk-install-scan"])    # GitHub does not know it: said, not an item

    def test_a_rev_that_is_not_in_main_s_history_is_not_an_item(self):
        self.history([OLD, MAIN])
        self.receipt("sheafmd", MID)
        deskinstall.scan()
        self.assertEqual(deskfile.items(), [])

    def test_scanning_twice_writes_once(self):
        self.found()
        before = deskfile.path().read_text()
        deskinstall.scan()
        self.assertEqual(deskfile.path().read_text(), before)
        self.assertEqual(self.events(), ["ready"])

    def test_github_down_changes_nothing(self):
        self.found()
        before = deskfile.path().read_text()
        (self.fake / "gh-down").write_text("")
        deskinstall.scan()
        self.assertEqual(deskfile.path().read_text(), before)
        self.assertTrue(self.errors)

    def test_main_moved_an_unticked_item_is_re_pinned(self):
        self.found()
        newer = "9" * 40
        self.history([OLD, MID, MAIN, newer])
        it = self.found()
        self.assertEqual(it.pinned, newer)
        self.assertEqual(len([i for i in deskfile.items()]), 1)
        self.assertIn("3 commits behind", it.block)

    def test_main_moving_keeps_the_thread_on_the_item(self):
        self.found()
        thread = '<!-- sheaf-comment id=c1 by="Thierry" at=2026-11-14T01:00 status=open quote="no recommendation yet."\nNot before the release.\n-->'
        deskfile.edit(lambda t: t.replace("no recommendation yet.\n", "no recommendation yet." + thread + "\n", 1))
        newer = "9" * 40
        self.history([OLD, MID, MAIN, newer])
        it = self.found()
        self.assertEqual(it.pinned, newer)
        self.assertIn(thread, deskfile.path().read_text())

    def test_main_moved_a_ticked_item_is_left_to_the_press(self):
        self.found()
        self.tick_box()
        self.history([OLD, MID, MAIN, "9" * 40])
        deskinstall.scan()
        self.assertEqual(self.item().pinned, MAIN)

    def test_a_tool_that_caught_up_drops_its_unticked_item_only(self):
        self.found()
        self.receipt("sheafmd", MAIN)
        deskinstall.scan()
        self.assertIsNone(self.item())
        self.assertEqual(self.events()[-1], "withdrawn")
        self.receipt("sheafmd", OLD)
        self.found()
        self.tick_box()
        self.receipt("sheafmd", MAIN)
        deskinstall.scan()
        self.assertIsNotNone(self.item())                       # ticked: the watcher decides, not the scan

    def test_a_finished_install_is_replaced_when_main_moves_again(self):
        self.found()
        self.tick_box()
        deskwatch.tick()
        self.assertEqual(self.events()[-1], "installed")
        self.history([OLD, MID, MAIN, "9" * 40])
        it = self.found()
        self.assertEqual((it.pinned, it.ticked), ("9" * 40, False))

    def test_scan_if_due_runs_at_most_once_per_interval_and_never_during_a_press(self):
        deskinstall._last_scan[0] = 0.0
        with deskwatch.press_lock() as got:
            self.assertTrue(got)
            deskinstall.scan_if_due()
        self.assertEqual(deskfile.items(), [])
        deskinstall.scan_if_due()
        self.assertEqual(len(deskfile.items()), 1)
        self.receipt("sheafmd", MAIN)
        deskinstall.scan_if_due()
        self.assertEqual(len(deskfile.items()), 1)              # not due again yet
        deskinstall._last_scan[0] = 0.0


class Press(Case):
    def press_it(self):
        self.found()
        self.tick_box()
        deskwatch.tick()
        return self.item()

    def test_installs_exactly_the_pinned_commit_then_restarts(self):
        it = self.press_it()
        uv = self.calls("uv.json")
        self.assertEqual(uv[0]["argv"], ["tool", "install", "--reinstall", "--from", f"git+https://github.com/{REPO}@{MAIN}", "sheafmd"])
        self.assertEqual([o for o in self.order() if o.startswith(("uv", "sheaf stop", "sheaf start"))],
                         ["uv", "sheaf stop", "sheaf start"])
        self.assertIn("  - Installed as 1a2b3c4 at ", it.block)
        self.assertTrue(it.ticked)
        self.assertIn("sheaf restarted", it.block)
        self.assertEqual(self.events(), ["ready", "pressing", "pressing", "installed"])
        self.assertEqual(desk.history("install:sheafmd")[-1]["sha"], MAIN)
        self.assertEqual(self.rev(), MAIN)
        self.assertIn("installed as 1a2b3c4", desk.status_line("install:sheafmd"))

    def test_main_moving_after_hand_over_still_installs_the_pinned_commit(self):
        self.found()
        self.tick_box()
        newer = "9" * 40
        self.history([OLD, MID, MAIN, newer])
        deskwatch.tick()
        self.assertEqual(self.calls("uv.json")[0]["argv"][4], f"git+https://github.com/{REPO}@{MAIN}")
        self.assertEqual(self.rev(), MAIN)

    def test_a_failed_install_leaves_the_old_one_and_says_so_and_never_restarts(self):
        self.found()
        self.tick_box()
        (self.fake / "uv-fails").write_text("")
        deskwatch.tick()
        it = self.item()
        self.assertFalse(it.ticked)
        self.assertIn("Not installed: uv failed", it.block)
        self.assertIn("Failed to build", it.block)
        self.assertIn(f"the old install ({OLD[:7]}) is still in place", it.block)
        self.assertEqual([o for o in self.order() if o.startswith("sheaf")], [])
        self.assertEqual(self.events()[-1], "refused")
        self.assertEqual(self.rev(), OLD)

    def test_a_press_after_a_refusal_tries_again(self):
        self.found()
        self.tick_box()
        (self.fake / "uv-fails").write_text("")
        deskwatch.tick()
        (self.fake / "uv-fails").unlink()
        self.tick_box()
        deskwatch.tick()
        self.assertEqual(self.events()[-1], "installed")
        self.assertEqual(self.rev(), MAIN)
        self.assertEqual(self.item().block.count("\n  - Not installed"), 0)      # the old result was replaced

    def test_a_lost_receipt_after_a_failure_is_said(self):
        self.found()
        self.tick_box()
        (self.fake / "uv-fails").write_text("")
        shutil.rmtree(self.tools / "sheafmd")
        deskwatch.tick()
        self.assertIn("no uv receipt", self.item().block)

    def test_the_restart_never_happens_when_uv_ends_with_another_commit_in_the_receipt(self):
        self.found()
        self.tick_box()
        (self.fake / "uv-kills-receipt").write_text("")
        deskwatch.tick()
        self.assertIn("Not installed: uv finished but the receipt says nothing", self.item().block)
        self.assertEqual([o for o in self.order() if o.startswith("sheaf")], [])

    def test_a_failed_stop_does_not_start_and_says_the_old_sheaf_may_run(self):
        self.found()
        self.tick_box()
        (self.fake / "sheaf-stop-fails").write_text("")
        deskwatch.tick()
        it = self.item()
        self.assertIn("Installed as 1a2b3c4", it.block)
        self.assertIn("the restart failed (sheaf stop failed, so the running sheaf may still be the old one", it.block)
        self.assertEqual([o for o in self.order() if o.startswith("sheaf")], ["sheaf status", "sheaf stop"])
        self.assertEqual(self.events()[-1], "installed")
        self.assertFalse(desk.history("install:sheafmd")[-1]["restarted"])

    def test_a_failed_start_is_said(self):
        self.found()
        self.tick_box()
        (self.fake / "sheaf-start-fails").write_text("")
        deskwatch.tick()
        self.assertIn("sheaf start failed after sheaf stop", self.item().block)
        self.assertIn("no hub is running now", self.item().block)

    def test_a_tool_already_at_the_pinned_commit_is_not_installed_again(self):
        self.found()
        self.tick_box()
        self.receipt("sheafmd", MAIN)
        deskwatch.tick()
        self.assertIn("Already installed as 1a2b3c4", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_an_install_done_by_hand_meanwhile_is_never_gone_back_over(self):
        self.found()
        self.tick_box()
        self.history([OLD, MID, MAIN, NEWER])
        self.receipt("sheafmd", NEWER)
        deskwatch.tick()
        self.assertIn("Not installed: the installed commit changed", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])
        self.assertEqual(self.rev(), NEWER)

    def test_a_github_that_cannot_be_asked_refuses_before_uv(self):
        self.found()
        self.tick_box()
        (self.fake / "gh-down").write_text("")
        deskwatch.tick()
        self.assertIn("Not installed: GitHub could not compare", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_a_receipt_of_an_unknown_shape_at_press_time_is_refused(self):
        self.found()
        self.tick_box()
        self.receipt("sheafmd", OLD, '[tool]\nrequirements = [{ name = "sheafmd", path = "/x" }]\n')
        deskwatch.tick()
        self.assertIn("no uv receipt of a known shape", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_an_item_with_no_pinned_commit_is_refused(self):
        self.found()
        deskfile.edit(lambda t: t.replace(f"Pinned commit: {MAIN}", "Pinned commit: none"))
        self.tick_box()
        deskwatch.tick()
        self.assertIn("Not installed: the item names no pinned commit", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_a_tool_with_no_restart_is_installed_and_nothing_is_restarted(self):
        self.history([OLD, MID, MAIN], "tiroir/thing")
        self.receipt("thingd", OLD, REAL_RECEIPT.replace("sweatshop-ai/sheaf", "tiroir/thing").replace("sheafmd", "thingd"))
        os.remove(self.tools / "sheafmd" / "uv-receipt.toml")
        deskinstall.scan()
        self.tick_box("install:thingd")
        deskwatch.tick()
        self.assertEqual(self.order().count("uv"), 1)
        self.assertEqual([o for o in self.order() if o.startswith("sheaf")], [])
        self.assertIn("  - Installed as 1a2b3c4 at ", self.item("install:thingd").block)

    def test_a_second_press_after_a_refusal_survives_a_scan(self):
        self.found()
        self.tick_box()
        (self.fake / "uv-fails").write_text("")
        deskwatch.tick()
        self.tick_box()                                         # ticked again; the watcher has not run yet
        deskinstall.scan()
        it = self.item()
        self.assertTrue(it.ticked)
        self.assertIn("Not installed", it.block)
        self.assertEqual(self.events(), ["ready", "pressing", "refused"])

    def test_a_pin_that_is_not_on_main_is_refused(self):
        self.found()
        deskfile.put_item("install:sheafmd", self.item().block.replace(f"Pinned commit: {MAIN}", f"Pinned commit: {NEWER}"), section="install")
        self.tick_box()
        deskwatch.tick()
        self.assertIn("Not installed: GitHub could not compare", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_a_pin_ahead_of_main_is_refused_by_the_main_check(self):
        self.history([OLD, MID, MAIN, NEWER])
        (self.fake / "main-sweatshop-ai_sheaf.txt").write_text(MAIN)      # main is MAIN: NEWER is on some branch
        self.found()
        deskfile.put_item("install:sheafmd", self.item().block.replace(f"Pinned commit: {MAIN}", f"Pinned commit: {NEWER}"), section="install")
        self.tick_box()
        deskwatch.tick()
        self.assertIn(f"Not installed: the pinned commit {NEWER[:7]} is not on {REPO}'s main", self.item().block)
        self.assertEqual(self.calls("uv.json"), [])

    def test_a_press_taken_back_before_uv_runs_installs_nothing_and_writes_nothing(self):
        self.found()
        self.tick_box()
        real = deskinstall.exe
        def untick_then_exe(name):
            deskfile.edit(lambda t: t.replace("- [x] Install sheafmd", "- [ ] Install sheafmd"))
            return real(name)
        deskinstall.exe = untick_then_exe
        self.addCleanup(setattr, deskinstall, "exe", real)
        deskwatch.tick()
        self.assertEqual(self.calls("uv.json"), [])
        self.assertNotIn("Not installed", self.item().block)
        self.assertEqual(self.events()[-1], "refused")

    def test_the_second_tick_does_not_install_again(self):
        self.press_it()
        deskwatch.tick()
        self.assertEqual(self.order().count("uv"), 1)

    def test_uv_and_sheaf_are_absolute_and_the_child_path_is_the_system_one(self):
        os.environ["PATH"] = f"{self.tmp / 'evil'}:{os.environ['PATH']}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", os.environ["PATH"].split(":", 1)[1]))
        (self.tmp / "evil").mkdir()
        planted = script(self.tmp / "evil" / "uv", f"#!{sys.executable}\nopen('{self.tmp}/planted', 'w').write('ran')\n")
        script(self.tmp / "evil" / "sheaf", f"#!{sys.executable}\nopen('{self.tmp}/planted', 'w').write('ran')\n")
        self.assertTrue(os.path.isabs(deskinstall.EXES["uv"]) and os.path.isabs(planted))
        self.press_it()
        self.assertFalse((self.tmp / "planted").exists())
        self.assertEqual(self.calls("uv.json")[0]["path"], deskinstall.SYSTEM_PATH)

    def test_a_tool_not_found_is_said_with_the_folders_looked_in(self):
        deskinstall.EXES = {**deskinstall.EXES, "uv": None}
        self.found()
        self.tick_box()
        deskwatch.tick()
        self.assertRegex(self.item().block, r"Not installed: uv was not found in .*/\.local/bin, /usr/local/bin, /usr/bin, /bin")

    def test_the_real_exes_are_resolved_absolute_or_missing(self):
        for name in ("uv", "sheaf"):
            real = shutil.which(name, path=deskinstall.SEARCH)
            self.assertIn(real, (None,) if real is None else (real,))
            if real:
                self.assertTrue(os.path.isabs(real))
        self.assertTrue(deskinstall.SEARCH.endswith(deskwatch.SYSTEM_PATH))


class Restart(Case):
    def test_the_restart_runs_in_the_environment_the_hub_runs_in(self):
        hub = subprocess.Popen(["sleep", "30"], env={"SHEAF_HOME": "/hub/home", "SHEAF_PORT": "31999", "PATH": os.environ["PATH"],
                                            "FAKE_DIR": str(self.fake), "UV_TOOL_DIR": str(self.tools)})
        self.addCleanup(hub.kill)
        self.addCleanup(hub.wait)
        (self.fake / "hub.pid").write_text(str(hub.pid))
        os.environ["SHEAF_PORT"] = "1111"                       # the service's own, which is not the hub's
        self.addCleanup(os.environ.pop, "SHEAF_PORT")
        self.assertEqual(deskinstall.restart_sheaf(), (True, ""))
        seen = [c for c in self.calls("sheaf.json") if c["cmd"] in ("stop", "start")]
        self.assertEqual([(c["cmd"], c["home"], c["port"]) for c in seen],
                         [("stop", "/hub/home", "31999"), ("start", "/hub/home", "31999")])

    def test_with_no_hub_running_the_services_sheaf_variables_are_not_passed(self):
        os.environ["SHEAF_PORT"] = "1111"
        self.addCleanup(os.environ.pop, "SHEAF_PORT")
        deskinstall.restart_sheaf()
        self.assertEqual({c["port"] for c in self.calls("sheaf.json") if c["cmd"] in ("stop", "start")}, {None})

    def test_start_goes_through_a_user_scope_when_there_is_one_and_never_falls_back_to_a_plain_start(self):
        scope = script(self.bin / "systemd-run", f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_DIR"] + "/scope.json", "a").write(repr(sys.argv[1:]) + "\\n")
sys.exit(1 if os.path.exists(os.environ["FAKE_DIR"] + "/scope-fails") else os.execv(sys.argv[sys.argv.index("--") + 1], sys.argv[sys.argv.index("--") + 1:]))
""")
        deskinstall.EXES = {**deskinstall.EXES, "systemd-run": scope}
        self.assertEqual(deskinstall.restart_sheaf(), (True, ""))
        self.assertIn("'--user', '--scope'", (self.fake / "scope.json").read_text())
        self.assertEqual(self.order().count("sheaf start"), 1)
        (self.fake / "scope-fails").write_text("")
        ok, why = deskinstall.restart_sheaf()
        self.assertFalse(ok)                                    # said, and no plain start inside AgentView's own cgroup
        self.assertIn("sheaf start failed", why)
        self.assertEqual(self.order().count("sheaf start"), 1)


class Shared(Case):
    def test_one_at_a_time_with_merge_presses(self):
        with deskwatch.press_lock() as got:
            self.assertTrue(got)
            self.found()
            self.tick_box()
            deskwatch.tick()
        self.assertEqual(self.calls("uv.json"), [])
        self.assertEqual(self.events(), ["ready"])
        deskwatch.tick()
        self.assertEqual(self.events()[-1], "installed")

    def test_a_merge_and_an_install_in_one_tick_go_one_after_the_other_in_page_order(self):
        (self.fake / "pr.json").write_text("")
        self.found()
        k = "sweatshop-ai/sheaf#5"
        with deskfile.locked():
            deskfile.put_item(k, desk.item_block(REPO, 5, "x", "merge", "", "a" * 40, "main", None, "S", "2026-11-13 10:40"))
            desk.log("ready", k, pinned="a" * 40)
        self.tick_box()
        deskfile.edit(lambda t: t.replace(f"- [ ] Merge {k}:", f"- [x] Merge {k}:"))
        deskwatch.tick()                                        # the Install section is the page's last: the merge goes first
        self.assertEqual([o for o in self.order() if o.startswith(("uv", "gh pr"))], ["gh pr view", "uv"])

    def test_two_items_with_one_key_press_neither(self):
        self.found()
        text = deskfile.path().read_text()
        deskfile.path().write_text(text + "\n" + text[text.index("- [ ] Install"):])
        deskfile.edit(lambda t: t.replace("- [ ] Install sheafmd", "- [x] Install sheafmd"))
        deskwatch.tick()
        self.assertEqual(self.calls("uv.json"), [])


class Recovery(Case):
    def begin(self):
        self.found()
        self.tick_box()
        with deskfile.locked():
            desk.log("pressing", "install:sheafmd", pinned=MAIN)

    def test_a_press_that_installed_but_never_recorded_is_settled_with_the_restart_hint_and_installs_nothing(self):
        self.begin()
        self.receipt("sheafmd", MAIN)
        deskwatch.tick()
        it = self.item()
        self.assertIn("Installed as 1a2b3c4", it.block)
        self.assertIn("run sheaf stop, then sheaf start", it.block)
        self.assertEqual(self.calls("uv.json"), [])
        self.assertEqual([o for o in self.order() if o.startswith("sheaf")], [])
        self.assertEqual(self.events()[-1], "installed")
        self.assertTrue(desk.history("install:sheafmd")[-1]["recovered"])

    def test_a_press_that_never_got_to_install_is_refused_after_the_grace_and_not_before(self):
        self.begin()
        deskinstall.GRACE = 3600
        deskwatch.recover()
        self.assertEqual(self.events()[-1], "pressing")
        deskinstall.GRACE = 0
        deskwatch.recover()
        self.assertIn("Not installed: the install was interrupted", self.item().block)
        self.assertFalse(self.item().ticked)
        self.assertEqual(self.calls("uv.json"), [])


if __name__ == "__main__":
    unittest.main()
