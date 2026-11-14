"""The merge desk's daily scan and tidy: PRs nobody handed over come onto the desk, settled items leave it.

Everything runs against a throwaway folder: `XDG_STATE_HOME`, `XDG_RUNTIME_DIR` and `UV_TOOL_DIR` under it, and
`deskwatch.GH` set to a fake `gh` that reads each repo's PRs from a file and writes every call to `calls.jsonl`.
The real desk file, the real GitHub and the real sheaf hub are never touched.
"""
import datetime
import json
import threading
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desk
import deskfile
import deskinstall
import deskscan
import deskwatch

HEAD = "a" * 40
OLD = "878d3e77407a348244713d8c87de7db4ed6cd171"
MAIN = "1a2b3c4" + "d" * 33
REPO = "sweatshop-ai/sheaf"
OTHER = "tiroir/agentview-demo"
HOUR = 3600

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
d = os.environ["FAKE_DIR"]
a = sys.argv[1:]
open(d + "/calls.jsonl", "a").write(json.dumps(a) + "\\n")
if a[:2] != ["pr", "list"]:
    sys.exit(9)
repo = a[a.index("-R") + 1].replace("/", "_")
if os.path.exists(d + "/down-" + repo):
    print("HTTP 502", file=sys.stderr); sys.exit(1)
print(open(d + "/prs-" + repo + ".json").read())
"""


def script(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def stamp(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setUpModule():
    global _runtime
    _runtime = tempfile.mkdtemp()
    os.environ["XDG_RUNTIME_DIR"] = _runtime


def tearDownModule():
    os.environ.pop("XDG_RUNTIME_DIR", None)
    shutil.rmtree(_runtime, True)


def check(conclusion="SUCCESS", status="COMPLETED"):
    return {"__typename": "CheckRun", "name": "ci", "status": status, "conclusion": conclusion}


def pr(n, age_h=30, checks=None, mergeable="MERGEABLE", draft=False, title="Fix the thing", head=None, base="main"):
    return {"number": n, "title": title, "headRefOid": head or f"{n:x}".rjust(40, "b"), "baseRefName": base,
            "createdAt": stamp(time.time() - age_h * HOUR), "mergeable": mergeable, "isDraft": draft,
            "statusCheckRollup": [check()] if checks is None else checks}


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
        self.saved = (deskwatch.GH, deskwatch.log.error, deskscan.PER_REPO, deskscan.TOTAL, deskscan.MAX_REPOS, desk.pr_head)
        desk.pr_head = lambda r, num: ("OPEN", f"{num:x}".rjust(40, "b"), "main")
        self.errors = []
        deskwatch.GH = script(self.bin / "gh", FAKE_GH)
        deskwatch.log.error = lambda *a, **k: self.errors.append((a, k))
        self.addCleanup(self.restore)

    def restore(self):
        deskwatch.GH, deskwatch.log.error, deskscan.PER_REPO, deskscan.TOTAL, deskscan.MAX_REPOS, desk.pr_head = self.saved

    def prs(self, repo, *prs):
        (self.fake / f"prs-{repo.replace('/', '_')}.json").write_text(json.dumps(list(prs)))

    def down(self, repo):
        (self.fake / f"down-{repo.replace('/', '_')}").write_text("")

    def calls(self):
        f = self.fake / "calls.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def item(self, k):
        return next((i for i in deskfile.items() if i.key == k), None)

    def keys(self):
        return [i.key for i in deskfile.items()]

    def page(self):
        f = deskfile.path()
        return f.read_text() if f.exists() else ""

    def events(self, k):
        return [r["event"] for r in desk.history(k)]

    def log_at(self, event, k, ago_h, **fields):
        """One record of the desk log, made `ago_h` hours ago."""
        p = desk.log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - ago_h * HOUR))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": at, "event": event, "key": k, **fields}) + "\n")

    def hand_over(self, repo, n, rec="merge"):
        desk.ready(repo, n, "handed over by a session", rec, "Opus GO")


class Found(Case):
    def test_a_green_mergeable_old_pr_nobody_handed_over_is_found(self):
        self.prs(REPO, pr(7))
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#7"])
        got = self.item(f"{REPO}#7")
        self.assertIsNotNone(got)
        self.assertFalse(got.ticked)
        self.assertEqual(got.pinned, "7".rjust(40, "b"))
        self.assertEqual(self.events(f"{REPO}#7"), ["ready"])

    def test_a_found_item_says_so_on_its_own_line_and_recommends_nothing(self):
        self.prs(REPO, pr(7, title="Cancel summary per thread"))
        deskscan.scan([REPO])
        block = self.item(f"{REPO}#7").block
        said = [l for l in block.splitlines() if "no recommendation yet" in l]
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].lstrip().startswith("- ") and "found" in said[0].lower())
        for verdict in ("merge.", "wait.", "don't merge", "Opus", "Codex", "GO"):
            self.assertNotIn("Recommendation: " + verdict, block)
        recs = [l for l in block.splitlines() if "Recommendation" in l]
        self.assertEqual(recs, [said[0]])                 # the one recommendation line IS the found line
        self.assertIn("Cancel summary per thread", block.splitlines()[0])

    def test_a_found_item_says_what_the_scan_read_itself(self):
        self.prs(REPO, pr(7, head="c" * 40))
        deskscan.scan([REPO])
        block = self.item(f"{REPO}#7").block
        self.assertIn("CI green on ccccccc, GitHub says MERGEABLE, opened ", block)

    def test_a_pr_handed_over_under_another_spelling_of_the_repo_is_not_found(self):
        self.hand_over("Sweatshop-AI/Sheaf", 7, rec="wait")
        self.prs(REPO, pr(7))
        self.assertEqual(deskscan.scan([REPO]), [])
        self.assertEqual(len(self.keys()), 1)
        self.assertIn("Recommendation: wait.", self.item("Sweatshop-AI/Sheaf#7").block)

    def test_the_scan_s_own_mixed_case_name_does_not_make_a_second_item_either(self):
        self.hand_over(REPO, 7, rec="wait")
        self.prs("Sweatshop-AI/Sheaf", pr(7))
        self.assertEqual(deskscan.scan(["Sweatshop-AI/Sheaf"]), [])
        self.assertEqual(self.keys(), [f"{REPO}#7"])

    def test_a_pr_with_only_a_log_record_under_another_spelling_is_not_found(self):
        self.log_at("withdrawn", "SWEATSHOP-AI/sheaf#7", 5)
        self.prs(REPO, pr(7))
        self.assertEqual(deskscan.scan([REPO]), [])

    def test_a_session_handing_over_a_found_pr_under_another_spelling_replaces_it(self):
        self.prs(REPO, pr(7))
        deskscan.scan([REPO])
        self.hand_over("Sweatshop-AI/Sheaf", 7, rec="wait")
        self.assertEqual(len(self.keys()), 1)
        self.assertNotIn("found by the scan", self.page())
        self.assertIn("Recommendation: wait.", self.page())

    def test_the_log_says_the_scan_found_it_and_what_it_pinned(self):
        self.prs(REPO, pr(7))
        deskscan.scan([REPO])
        rec = desk.history(f"{REPO}#7")[0]
        self.assertEqual((rec["event"], rec["by"], rec["pinned"]), ("ready", "AgentView's scan", "7".rjust(40, "b")))
        self.assertNotIn("rec", rec)

    def test_only_what_is_green_mergeable_open_and_old_is_found(self):
        self.prs(REPO,
                 pr(1), pr(2, age_h=23), pr(3, draft=True), pr(4, mergeable="CONFLICTING"),
                 pr(5, mergeable="UNKNOWN"), pr(6, checks=[]), pr(7, checks=[check("FAILURE")]),
                 pr(8, checks=[check("", "IN_PROGRESS")]), pr(9, checks=[check(), check("FAILURE")]),
                 pr(10, checks=[check("SKIPPED"), check("NEUTRAL"), check()]),
                 pr(11, checks=[{"__typename": "StatusContext", "state": "SUCCESS", "context": "x"}]),
                 pr(12, checks=[{"__typename": "StatusContext", "state": "PENDING", "context": "x"}]),
                 pr(13, checks=[check("CANCELLED")]), pr(14, checks=[check("STARTUP_FAILURE")]),
                 pr(15, checks=[check("TIMED_OUT")]), pr(16, checks=[check("ACTION_REQUIRED")]))
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#{n}" for n in (1, 10, 11)])

    def test_a_pr_with_no_readable_age_or_head_is_not_found(self):
        bad_age = pr(1)
        bad_age["createdAt"] = "yesterday"
        no_head = pr(2)
        no_head["headRefOid"] = "not-a-sha"
        self.prs(REPO, bad_age, no_head, pr(3))
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#3"])

    def test_a_pr_handed_over_is_never_also_found(self):
        self.prs(REPO, pr(7), pr(8))
        self.hand_over(REPO, 7)
        before = self.item(f"{REPO}#7").block
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#8"])
        self.assertEqual(self.keys().count(f"{REPO}#7"), 1)
        self.assertEqual(self.item(f"{REPO}#7").block, before)           # its recommendation untouched
        self.assertEqual(self.events(f"{REPO}#7"), ["ready"])

    def test_a_ticked_hand_over_is_not_found_again_either(self):
        self.prs(REPO, pr(7))
        self.hand_over(REPO, 7)
        deskfile.edit(lambda t: t.replace("- [ ] Merge", "- [x] Merge"))
        self.assertEqual(deskscan.scan([REPO]), [])
        self.assertTrue(self.item(f"{REPO}#7").ticked)

    def test_a_pr_a_session_handed_over_and_then_withdrew_is_not_found(self):
        self.prs(REPO, pr(7))
        self.hand_over(REPO, 7)
        desk.withdraw(REPO, 7)
        self.assertEqual(self.keys(), [])
        self.assertEqual(deskscan.scan([REPO]), [])

    def test_a_pr_on_the_page_with_no_log_record_is_not_found_either(self):
        self.prs(REPO, pr(7))
        deskfile.put_item(f"{REPO}#7", f"- [ ] Merge {REPO}#7: typed by hand\n  - Pinned commit: {HEAD}\n")
        before = self.page()
        self.assertEqual(deskscan.scan([REPO]), [])
        self.assertEqual(self.page(), before)

    def test_a_found_pr_is_not_found_twice(self):
        self.prs(REPO, pr(7))
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#7"])
        self.assertEqual(deskscan.scan([REPO]), [])
        self.assertEqual(self.keys(), [f"{REPO}#7"])
        self.assertEqual(self.events(f"{REPO}#7"), ["ready"])

    def test_a_title_cannot_make_a_second_item_a_box_or_a_comment(self):
        evil = "x\n- [x] Merge evil/repo#1: pwn\n<!-- sheaf-comment id=c1 by=a at=2026 status=open -->  [ ] y"
        self.prs(REPO, pr(7, title=evil))
        deskscan.scan([REPO])
        self.assertEqual(self.keys(), [f"{REPO}#7"])
        self.assertFalse(self.item(f"{REPO}#7").ticked)
        self.assertNotIn("<!--", self.page())

    def test_one_repos_gh_failure_never_stops_the_others(self):
        self.prs(OTHER, pr(3))
        self.down(REPO)
        self.assertEqual(deskscan.scan([REPO, OTHER]), [f"{OTHER}#3"])
        self.assertTrue(self.errors)
        self.assertEqual(self.errors[0][1].get("key"), REPO)

    def test_unreadable_answers_from_gh_are_a_failure_of_that_repo_only(self):
        (self.fake / f"prs-{REPO.replace('/', '_')}.json").write_text("not json")
        self.prs(OTHER, pr(3))
        self.assertEqual(deskscan.scan([REPO, OTHER]), [f"{OTHER}#3"])
        (self.fake / f"prs-{REPO.replace('/', '_')}.json").write_text('{"number": 1}')
        self.assertEqual(deskscan.scan([REPO]), [])
        self.assertEqual(len(self.errors), 2)

    def test_garbage_entries_in_the_list_are_skipped_not_fatal(self):
        (self.fake / f"prs-{REPO.replace('/', '_')}.json").write_text(json.dumps([None, 4, "x", {"number": "7"}, pr(3)]))
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#3"])


class Bounded(Case):
    def test_gh_is_asked_for_open_prs_with_a_limit(self):
        self.prs(REPO)
        deskscan.scan([REPO])
        (argv,) = self.calls()
        self.assertEqual(argv[:2], ["pr", "list"])
        self.assertEqual(argv[argv.index("-R") + 1], REPO)
        self.assertEqual(argv[argv.index("--state") + 1], "open")
        self.assertEqual(argv[argv.index("--limit") + 1], str(deskscan.PER_REPO))

    def test_no_more_than_the_cap_per_repo_is_read_whatever_gh_returns(self):
        deskscan.PER_REPO = 2
        self.prs(REPO, *[pr(n) for n in range(1, 8)])
        self.assertEqual(deskscan.scan([REPO]), [f"{REPO}#1", f"{REPO}#2"])

    def test_no_more_than_the_total_cap_is_found_in_all(self):
        deskscan.PER_REPO, deskscan.TOTAL = 2, 3
        for r in (REPO, OTHER, "tiroir/third"):
            self.prs(r, pr(1), pr(2))
        got = deskscan.scan([REPO, OTHER, "tiroir/third"])
        self.assertEqual(got, [f"{REPO}#1", f"{REPO}#2", f"{OTHER}#1"])

    def test_the_total_cap_counts_prs_read_not_only_those_found(self):
        deskscan.PER_REPO, deskscan.TOTAL = 3, 4
        self.prs(REPO, pr(1, age_h=1), pr(2, age_h=1), pr(3, age_h=1))
        self.prs(OTHER, pr(4), pr(5), pr(6))
        self.assertEqual(deskscan.scan([REPO, OTHER]), [f"{OTHER}#4"])

    def test_no_more_than_the_repo_cap_is_asked(self):
        deskscan.MAX_REPOS = 2
        for r in ("a/one", "a/two", "a/three", "a/four"):
            self.prs(r)
        deskscan.scan(["a/one", "a/two", "a/three", "a/four"])
        self.assertEqual([c[c.index("-R") + 1] for c in self.calls()], ["a/one", "a/two"])

    def test_a_repo_listed_twice_is_asked_once(self):
        self.prs(REPO)
        deskscan.scan([REPO, REPO])
        self.assertEqual(len(self.calls()), 1)

    def test_a_repo_name_that_is_not_owner_name_is_never_given_to_gh(self):
        deskscan.scan(["../etc", "-R", "a/b/c", "", None, "x y/z"])
        self.assertEqual(self.calls(), [])


class Daily(Case):
    def test_the_scan_runs_once_a_day(self):
        self.prs(REPO, pr(7))
        now = time.time()
        self.assertTrue(deskscan.run_if_due(now=now, repos=lambda: [REPO]))
        n = len(self.calls())
        self.assertGreater(n, 0)
        self.assertFalse(deskscan.run_if_due(now=now + 60, repos=lambda: [REPO]))
        self.assertFalse(deskscan.run_if_due(now=now + deskscan.DAY - 60, repos=lambda: [REPO]))
        self.assertEqual(len(self.calls()), n)
        self.assertTrue(deskscan.run_if_due(now=now + deskscan.DAY + 1, repos=lambda: [REPO]))

    def test_the_day_is_kept_on_disk_under_the_state_folder_and_survives_a_restart(self):
        self.prs(REPO, pr(7))
        now = time.time()
        deskscan.run_if_due(now=now, repos=lambda: [REPO])
        kept = list((self.tmp / "state").rglob("desk-scan.json"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].parent, deskfile.path().parent)
        import importlib
        fresh = importlib.reload(deskscan)               # a restart: nothing in memory
        n = len(self.calls())
        self.assertFalse(fresh.run_if_due(now=now + 3600, repos=lambda: [REPO]))
        self.assertEqual(len(self.calls()), n)

    def test_a_scan_that_dies_still_spends_the_day(self):
        now = time.time()

        def boom():
            raise RuntimeError("no roster")
        with self.assertRaises(RuntimeError):
            deskscan.run_if_due(now=now, repos=boom)
        self.assertFalse(deskscan.run_if_due(now=now + 60, repos=lambda: [REPO]))
        self.assertEqual(self.calls(), [])

    def test_an_unreadable_stamp_means_due_not_never(self):
        self.prs(REPO, pr(7))
        deskscan.stamp_path().parent.mkdir(parents=True, exist_ok=True)
        deskscan.stamp_path().write_text("garbage")
        self.assertTrue(deskscan.run_if_due(repos=lambda: [REPO]))

    def test_a_stamp_in_the_future_is_not_a_license_to_never_scan(self):
        self.prs(REPO, pr(7))
        now = time.time()
        deskscan.stamp_path().parent.mkdir(parents=True, exist_ok=True)
        deskscan.stamp_path().write_text(json.dumps({"at": now + 10 * deskscan.DAY}))
        self.assertTrue(deskscan.run_if_due(now=now, repos=lambda: [REPO]))

    def test_a_small_step_back_of_the_clock_does_not_run_the_day_again(self):
        self.prs(REPO, pr(7))
        now = time.time()
        deskscan.run_if_due(now=now, repos=lambda: [REPO])
        n = len(self.calls())
        self.assertFalse(deskscan.run_if_due(now=now - 1, repos=lambda: [REPO]))
        self.assertFalse(deskscan.run_if_due(now=now - 1800, repos=lambda: [REPO]))
        self.assertEqual(len(self.calls()), n)

    def test_a_day_with_no_repo_to_scan_is_tried_again_in_a_quarter_of_an_hour_not_tomorrow(self):
        self.prs(REPO, pr(7))
        now = time.time()
        self.assertTrue(deskscan.run_if_due(now=now, repos=lambda: []))
        self.assertEqual(self.calls(), [])
        self.assertFalse(deskscan.run_if_due(now=now + 60, repos=lambda: [REPO]))
        self.assertTrue(deskscan.run_if_due(now=now + deskscan.RETRY + 1, repos=lambda: [REPO]))
        self.assertEqual(self.keys(), [f"{REPO}#7"])
        self.assertFalse(deskscan.run_if_due(now=now + deskscan.RETRY + 120, repos=lambda: [REPO]))

    def test_the_default_repos_are_the_roster_s_plus_those_remembered(self):
        now = time.time()
        got = deskscan.known_repos(now, lambda: {"columns": [{"project": "repo:github.com/a/one"}]})
        self.assertEqual(got, ["a/one"])
        later = deskscan.known_repos(now + 5 * deskscan.DAY, lambda: {"columns": [{"project": "repo:github.com/a/two"}]})
        self.assertEqual(later, ["a/two", "a/one"])
        gone = deskscan.known_repos(now + 5 * deskscan.DAY + deskscan.KEEP,
                                    lambda: {"columns": [{"project": "repo:github.com/a/three"}]})
        self.assertEqual(gone, ["a/three"])

    def test_more_known_repos_than_a_day_may_ask_are_all_reached_over_the_days(self):
        deskscan.MAX_REPOS = 4
        ids = [f"repo:github.com/a/r{n:02d}" for n in range(10)]
        now = time.time()
        reached = set()
        for day in range(10):
            got = deskscan.known_repos(now + day * deskscan.DAY, lambda: {"columns": [{"project": i} for i in ids]})
            reached |= set(deskscan.clean(got))
        self.assertEqual(len(reached), 10)

    def test_a_stamp_that_cannot_be_written_is_not_tried_at_every_tick(self):
        saved = (deskscan.spend, deskscan.run_if_due, deskscan._blocked[0])
        calls = []
        deskscan.spend = lambda now: False
        try:
            self.assertFalse(deskscan.run_if_due(now=time.time(), repos=lambda: [REPO]))
            t = [x for x in threading.enumerate() if x.name == "desk-scan"]
            self.assertFalse(deskscan.scan_if_due())
            self.assertEqual([x for x in threading.enumerate() if x.name == "desk-scan"], t)
        finally:
            deskscan.spend, deskscan.run_if_due, deskscan._blocked[0] = saved

    def test_a_cold_roster_forgets_nothing_it_remembered(self):
        now = time.time()
        deskscan.known_repos(now, lambda: {"columns": [{"project": "repo:github.com/a/one"}]})
        self.assertEqual(deskscan.known_repos(now + 60, lambda: {"columns": []}), ["a/one"])
        self.assertEqual(deskscan.known_repos(now + 120, lambda: None), ["a/one"])

    def test_a_remembered_file_that_is_garbage_is_no_memory(self):
        deskscan.repos_path().parent.mkdir(parents=True, exist_ok=True)
        deskscan.repos_path().write_text('["x"]')
        self.assertEqual(deskscan.known_repos(time.time(), lambda: {"columns": []}), [])
        deskscan.repos_path().write_text('{"a/one": "yesterday", "a/two": true, "../x": 5}')
        self.assertEqual(deskscan.known_repos(time.time(), lambda: {"columns": []}), [])

    def test_the_watcher_s_call_returns_at_once_and_runs_one_scan_at_a_time(self):
        started, release, ran = threading.Event(), threading.Event(), []
        saved = deskscan.run_if_due

        def slow():
            ran.append(1)
            started.set()
            release.wait(10)
        deskscan.run_if_due = slow
        try:
            t0 = time.time()
            self.assertTrue(deskscan.scan_if_due())
            self.assertLess(time.time() - t0, 1)
            self.assertTrue(started.wait(5))
            self.assertFalse(deskscan.scan_if_due())             # one at a time
        finally:
            release.set()
            deskscan.run_if_due = saved
        for _ in range(100):
            if deskscan._running.acquire(blocking=False):
                deskscan._running.release()
                break
            time.sleep(0.05)
        self.assertEqual(ran, [1])

    def test_a_thread_that_fails_is_logged_and_lets_the_next_day_try(self):
        saved = deskscan.run_if_due

        def boom():
            raise RuntimeError("x")
        deskscan.run_if_due = boom
        try:
            self.assertTrue(deskscan.scan_if_due())
            for _ in range(100):
                if self.errors:
                    break
                time.sleep(0.05)
        finally:
            deskscan.run_if_due = saved
        self.assertTrue(self.errors)
        for _ in range(100):
            if deskscan._running.acquire(blocking=False):
                deskscan._running.release()
                break
            time.sleep(0.05)

    def test_the_day_run_tidies_as_well_as_scans(self):
        k = f"{REPO}#9"
        self.hand_over(REPO, 9)
        self.log_at("merged", k, 30, sha="c" * 40)
        deskfile.edit(lambda t: deskfile.settle(t, k, "Merged as ccccccc at 10:00"))
        self.prs(REPO, pr(7))
        deskscan.run_if_due(repos=lambda: [REPO])
        self.assertEqual(self.keys(), [f"{REPO}#7"])


class Wiring(Case):
    def test_the_watchers_loop_runs_the_daily_scan(self):
        calls = []
        saved = (deskwatch.tick, deskinstall.scan_if_due, deskscan.scan_if_due, deskwatch.time.sleep)

        def stop(_):
            raise KeyboardInterrupt
        deskwatch.tick, deskinstall.scan_if_due = lambda: None, lambda: None
        deskscan.scan_if_due = lambda: calls.append("scan")
        deskwatch.time.sleep = stop
        try:
            with self.assertRaises(KeyboardInterrupt):
                deskwatch.run()
        finally:
            deskwatch.tick, deskinstall.scan_if_due, deskscan.scan_if_due, deskwatch.time.sleep = saved
        self.assertEqual(calls, ["scan"])

    def test_a_scan_that_raises_does_not_kill_the_watcher(self):
        saved = (deskwatch.tick, deskinstall.scan_if_due, deskscan.scan_if_due, deskwatch.time.sleep)

        def boom():
            raise RuntimeError("x")

        def stop(_):
            raise KeyboardInterrupt
        deskwatch.tick, deskinstall.scan_if_due, deskscan.scan_if_due, deskwatch.time.sleep = lambda: None, lambda: None, boom, stop
        try:
            with self.assertRaises(KeyboardInterrupt):
                deskwatch.run()
        finally:
            deskwatch.tick, deskinstall.scan_if_due, deskscan.scan_if_due, deskwatch.time.sleep = saved
        self.assertTrue(self.errors)


class Repos(Case):
    def column(self, *ids):
        return {"columns": [{"project": i, "sessions": []} for i in ids]}

    def test_the_repos_are_those_of_the_projects_on_the_page(self):
        got = deskscan.project_repos(lambda: self.column(
            "repo:github.com/sweatshop-ai/sheaf", "track:merge-desk", "folder:x", "client:acme",
            "repo:github.com/tiroir/apex", "repo:github.com/sweatshop-ai/sheaf"))
        self.assertEqual(got, ["sweatshop-ai/sheaf", "tiroir/apex"])

    def test_a_repo_on_another_host_is_not_asked_of_github(self):
        got = deskscan.project_repos(lambda: self.column("repo:gitlab.com/a/b", "repo:github.com/a/b", "repo:ghe.corp/a/c"))
        self.assertEqual(got, ["a/b"])

    def test_odd_project_ids_are_dropped(self):
        got = deskscan.project_repos(lambda: self.column(
            "repo:github.com/a", "repo:github.com/a/b/c", "repo:github.com/../x", "repo:github.com/-a/b",
            "repo:github.com/ok/fine", None, 7))
        self.assertEqual(got, ["ok/fine"])

    def test_no_roster_means_no_repos_not_a_crash(self):
        def boom():
            raise OSError("providers down")
        self.assertEqual(deskscan.project_repos(boom), [])
        self.assertEqual(deskscan.project_repos(lambda: {"columns": "x"}), [])
        self.assertEqual(deskscan.project_repos(lambda: None), [])


COMMENT_OPEN = '<!-- sheaf-comment id=c1 by="Ada" at=2026-11-14T09:00 status=open quote="the thing" -->'
COMMENT_DONE = '<!-- sheaf-comment id=c1 by="Ada" at=2026-11-14T09:00 status=resolved quote="the thing" -->'


class Tidy(Case):
    def merged(self, n=9, ago_h=30, repo=REPO):
        k = f"{repo}#{n}"
        self.hand_over(repo, n)
        deskfile.edit(lambda t: deskfile.settle(t, k, "Merged as ccccccc at 10:00"))
        self.log_at("merged", k, ago_h, sha="c" * 40)
        return k

    def test_a_merged_item_older_than_a_day_leaves(self):
        k = self.merged()
        self.assertEqual(deskscan.tidy(), [k])
        self.assertEqual(self.keys(), [])

    def test_a_merged_item_younger_than_a_day_stays_so_the_person_sees_it(self):
        k = self.merged(ago_h=23)
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), [k])

    def test_the_log_says_it_was_tidied_and_status_still_says_merged(self):
        k = self.merged()
        deskscan.tidy()
        self.assertEqual(self.events(k)[-1], "tidied")
        self.assertIn("merged as ccccccc", "\n".join(desk.status_all()))

    def test_a_withdrawn_item_still_on_the_page_leaves_after_a_day(self):
        k = f"{REPO}#4"
        self.hand_over(REPO, 4)
        self.log_at("withdrawn", k, 30)
        self.assertEqual(deskscan.tidy(), [k])
        k2 = f"{REPO}#5"
        self.hand_over(REPO, 5)
        self.log_at("withdrawn", k2, 2)
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), [k2])

    def test_a_waiting_refused_or_pressing_item_is_never_tidied_however_old(self):
        for n, ev in ((1, "ready"), (2, "refused"), (3, "pressing")):
            self.hand_over(REPO, n)
            self.log_at(ev, f"{REPO}#{n}", 500, pinned="x", why="y")
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(len(self.keys()), 3)

    def test_a_merged_item_handed_over_again_is_waiting_not_tidied(self):
        k = self.merged()
        self.hand_over(REPO, 9)
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), [k])

    def test_a_merged_log_line_without_a_result_on_the_page_keeps_the_item(self):
        k = f"{REPO}#9"
        self.hand_over(REPO, 9)
        self.log_at("merged", k, 30, sha="c" * 40)
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), [k])

    def test_an_item_with_no_log_at_all_stays(self):
        k = self.merged()
        desk.log_path().unlink()
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), [k])

    def test_a_log_time_that_cannot_be_read_is_never_old(self):
        k = self.merged()
        with open(desk.log_path(), "a") as fh:
            fh.write(json.dumps({"at": "whenever", "event": "merged", "key": k}) + "\n")
            fh.write(json.dumps({"event": "merged", "key": k}) + "\n")
        self.assertEqual(deskscan.tidy(), [])

    def test_the_other_items_come_out_byte_for_byte(self):
        keep = f"{REPO}#1"
        self.hand_over(REPO, 1)
        gone = self.merged(9)
        self.hand_over(REPO, 2)
        before = self.page()
        want = deskfile.drop(before, gone)
        deskscan.tidy()
        self.assertEqual(self.page(), want)
        self.assertIn(keep, self.keys())

    def test_a_key_that_is_on_the_page_twice_is_left_alone(self):
        k = self.merged()
        deskfile.path().write_text(self.page() + self.item(k).block)
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys().count(k), 2)

    def swallowed(self, mark):
        k = self.merged(1)
        self.hand_over(REPO, 2, rec="merge")
        deskfile.path().write_text(self.page().replace("handed over by a session", "handed over by a session " + mark, 1))
        return k

    def test_text_that_the_page_reads_as_an_opening_comment_never_takes_the_next_item_with_it(self):
        for mark in (r"write \<!-- to open one", "the `<!--` mark", "an open <!-- never closed"):
            self.setUp_again()
            self.swallowed(mark)
            before = self.page()
            self.assertEqual(deskscan.tidy(), [], mark)
            self.assertEqual(self.page(), before)
            self.assertIn(f"{REPO}#2", before)

    def setUp_again(self):
        shutil.rmtree(self.tmp / "state", True)

    def test_a_stray_comment_mark_closed_by_a_later_arrow_still_keeps_the_item_below(self):
        k = self.merged(1)
        self.hand_over(REPO, 2, rec="merge")
        resolved = COMMENT_DONE
        text = self.page().replace("handed over by a session", r"write \<!-- here", 1)
        head, _, tail = text.rpartition("Handed over by a session")          # the last one: item 2's own line
        text = head + "Handed over by a session " + resolved + tail
        deskfile.path().write_text(text)
        before = self.page()
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.page(), before)
        self.assertIn(f"{REPO}#2", before)
        deskfile.path().write_text(self.page().replace(r"write \<!-- here", "dev --> main"))
        self.assertEqual(deskscan.tidy(), [k])      # an arrow typed as text does not stop a clean item going

    def test_a_block_with_a_heading_or_list_line_of_its_own_is_not_whole(self):
        self.assertFalse(deskscan.whole("- [ ] Merge a/b#1: x\n## Later\n"))
        self.assertFalse(deskscan.whole("- [ ] Merge a/b#1: x\n- note\n"))
        self.assertFalse(deskscan.whole("- [ ] Merge a/b#1: x\n* note\n"))
        self.assertTrue(deskscan.whole("- [ ] Merge a/b#1: x\n  - note\n\ntext\n"))

    def test_an_item_whose_block_holds_another_items_task_line_is_not_dropped(self):
        self.assertFalse(deskscan.whole("- [ ] Merge a/b#1: x\n  - y\n- [ ] Merge a/b#2: z\n"))
        self.assertTrue(deskscan.whole("- [ ] Merge a/b#1: x" + COMMENT_DONE + "\n  - y\n"))
        self.assertFalse(deskscan.whole("- [ ] Merge a/b#1: x\n  - y <!-- open\n"))

    def test_a_thread_written_between_the_look_and_the_drop_is_seen(self):
        k = self.merged()
        real = deskfile.edit

        def sneaky(change, file=None):
            deskfile.path().write_text(self.page().replace("Merged as ccccccc", "Merged as ccccccc" + COMMENT_OPEN, 1))
            return real(change, file)
        deskfile.edit = sneaky
        try:
            self.assertEqual(deskscan.tidy(), [])
        finally:
            deskfile.edit = real
        self.assertEqual(self.keys(), [k])
        self.assertNotIn("tidied", self.events(k))

    def test_tidying_twice_is_the_same_as_once(self):
        self.merged()
        self.assertEqual(len(deskscan.tidy()), 1)
        after = self.page()
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.page(), after)

    def test_an_empty_or_missing_desk_is_not_an_error(self):
        self.assertEqual(deskscan.tidy(), [])
        self.assertFalse(deskfile.path().exists())


class Threads(Case):
    """An item with a comment thread open in any shape sheaf stores is never tidied; the shapes are those of
    sheafmd/comments.py: inline after text, on a line of its own, the one-line `<br>` form, several lines,
    the older `rd-comment` marker, an orphan, a thread with replies."""

    def settled(self, mark, where="sub"):
        """A merged item 30 h old whose page text has `mark` in it, at `where`."""
        k = f"{REPO}#9"
        self.hand_over(REPO, 9)
        deskfile.edit(lambda t: deskfile.settle(t, k, "Merged as ccccccc at 10:00"))
        self.log_at("merged", k, 30, sha="c" * 40)
        lines_ = self.page().split("\n")
        i = next(n for n, l in enumerate(lines_) if "Merge " in l and "#9" in l)
        if where == "task":
            lines_[i] += mark
        elif where == "sub":
            lines_[i + 1] += mark
        elif where == "own":
            lines_.insert(i + 2, mark)
        elif where == "last":
            lines_.insert(len([l for l in lines_ if l.strip()]), mark)
        deskfile.path().write_text("\n".join(lines_))
        return k

    def kept(self, mark, where="sub"):
        self.settled(mark, where)
        before = self.page()
        self.assertEqual(deskscan.tidy(), [], mark)
        self.assertEqual(self.page(), before)

    def gone(self, mark, where="sub"):
        k = self.settled(mark, where)
        self.assertEqual(deskscan.tidy(), [k], mark)

    def test_open_inline_after_the_task_line(self):
        self.kept(COMMENT_OPEN, "task")

    def test_open_inline_after_a_sub_line(self):
        self.kept(COMMENT_OPEN, "sub")

    def test_open_on_a_line_of_its_own(self):
        self.kept(COMMENT_OPEN, "own")

    def test_open_after_the_last_line_of_the_item(self):
        self.kept(COMMENT_OPEN, "last")

    def test_open_on_several_lines_with_replies(self):
        self.kept('<!-- sheaf-comment id=c2 by="Thierry" at=2026-11-14T09:00 status=open quote="x"\nIs this safe?\n'
                  '@Claude 2026-11-14T09:30 answer: Yes.\n- looks like a list\n# and a heading\n-->', "own")

    def test_open_in_the_one_line_br_form(self):
        self.kept('<!-- sheaf-comment id=c3 by="T" at=2026-11-14T09:00 status=open quote="x"<br>why?<br>@Claude 2026-11-14T09:30: because -->')

    def test_open_with_the_older_rd_comment_marker(self):
        self.kept('<!-- rd-comment id=c4 by="Ada" at=2026-09-19T14:02 status=open quote="q" -->')

    def test_open_orphan(self):
        self.kept('<!-- sheaf-comment id=c5 by="Ada" at=2026-09-19T14:02 status=open orphan=1 quote="q" -->')

    def test_no_status_means_open(self):
        self.kept('<!-- sheaf-comment id=c6 by="Ada" at=2026-09-19T14:02 quote="q" -->')

    def test_a_status_we_do_not_know_is_kept_open(self):
        self.kept('<!-- sheaf-comment id=c7 by="Ada" at=2026-09-19T14:02 status=pending quote="q" -->')
        self.kept('<!-- sheaf-comment id=c7 by="Ada" at=2026-09-19T14:02 status=Resolved quote="q" -->')

    def test_a_comment_we_cannot_read_is_kept(self):
        self.kept('<!-- sheaf-comment by="Ada" at=2026-09-19T14:02 status=resolved quote="q" -->')               # no id
        self.kept('<!-- sheaf-comment id=c8 status=resolved status=open quote="q" -->')                        # duplicate key
        self.kept('<!--sheaf-comment id=c8 status=resolved')                                                   # never closed

    def test_one_open_among_resolved_keeps_the_item(self):
        self.kept(COMMENT_DONE + " and " + COMMENT_OPEN.replace("c1", "c9"))

    def test_a_status_word_inside_a_quoted_value_does_not_decide(self):
        self.kept('<!-- sheaf-comment id=c1 by="x status=resolved" at=2026-11-14T09:00 status=open quote="y" -->')
        self.kept('<!-- sheaf-comment id=c1 by="a" at=2026-11-14T09:00 status=open quote="status=resolved" -->')

    def test_a_status_word_in_a_replys_text_does_not_decide(self):
        self.kept('<!-- sheaf-comment id=c1 by="a" at=2026-11-14T09:00 status=open quote="q"\n@Claude 2026-11-14T09:30: set status=resolved\n-->', "own")

    def test_a_resolved_thread_is_closed_and_the_item_may_go(self):
        self.gone(COMMENT_DONE)
        self.gone('<!-- rd-comment id=c4 by="Ada" at=2026-09-19T14:02 status=resolved quote="q" -->', "own")

    def test_a_comment_that_merely_quotes_the_marker_in_item_text_is_still_not_tidied(self):
        k = f"{REPO}#9"
        self.hand_over(REPO, 9, rec="merge")
        deskfile.edit(lambda t: deskfile.settle(t, k, "Merged as ccccccc at 10:00"))
        self.log_at("merged", k, 30, sha="c" * 40)
        deskfile.path().write_text(self.page().replace("handed over by a session", "see <!-- sheaf-comment id=z status=open"))
        self.assertEqual(deskscan.tidy(), [])

    def test_an_open_thread_on_one_item_does_not_save_its_neighbour(self):
        k1 = f"{REPO}#8"
        self.hand_over(REPO, 8)
        deskfile.edit(lambda t: deskfile.settle(t, k1, "Merged as ccccccc at 10:00"))
        self.log_at("merged", k1, 30, sha="c" * 40)
        k2 = self.settled(COMMENT_OPEN, "sub")
        self.assertEqual(deskscan.tidy(), [k1])
        self.assertEqual(self.keys(), [k2])


class InstallItems(Case):
    RECEIPT = '[tool]\nrequirements = [{{ name = "sheafmd", git = "https://github.com/sweatshop-ai/sheaf?rev={rev}" }}]\nentrypoints = []\n'

    def receipt(self, rev):
        d = self.tools / "sheafmd"
        d.mkdir(parents=True, exist_ok=True)
        (d / "uv-receipt.toml").write_text(self.RECEIPT.format(rev=rev))

    def installed_item(self, ago_h=30, pinned=MAIN):
        block = deskinstall.item_block(deskinstall.Tool("sheafmd", "sheafmd", REPO, OLD), pinned, 3, "2026-11-12 10:00")
        deskfile.put_item("install:sheafmd", block, section="install")
        deskfile.edit(lambda t: deskfile.settle(t, "install:sheafmd", f"Installed as {pinned[:7]} at 10:00"))
        self.log_at("installed", "install:sheafmd", ago_h, sha=pinned)

    def test_an_install_item_that_is_installed_and_at_its_pin_leaves(self):
        self.receipt(MAIN)
        self.installed_item()
        self.assertEqual(deskscan.tidy(), ["install:sheafmd"])

    def test_an_install_item_whose_restart_failed_stays_for_the_person_to_read(self):
        self.receipt(MAIN)
        self.installed_item()
        deskfile.edit(lambda t: deskfile.settle(t, "install:sheafmd", f"Installed as {MAIN[:7]} at 10:00; the restart failed (no hub is running now)"))
        self.assertEqual(deskscan.tidy(), [])
        deskfile.edit(lambda t: deskfile.settle(t, "install:sheafmd", f"Installed as {MAIN[:7]} at 10:00; the restart may not have run: run sheaf stop, then sheaf start"))
        self.assertEqual(deskscan.tidy(), [])

    def test_an_install_item_still_behind_is_never_tidied(self):
        self.receipt(OLD)                                   # the receipt still names the old commit
        self.installed_item()
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), ["install:sheafmd"])

    def test_an_install_item_whose_tool_is_gone_or_unreadable_stays(self):
        self.installed_item()
        self.assertEqual(deskscan.tidy(), [])
        self.receipt(MAIN)
        (self.tools / "sheafmd" / "uv-receipt.toml").write_text("not toml [[")
        self.assertEqual(deskscan.tidy(), [])
        self.assertEqual(self.keys(), ["install:sheafmd"])

    def test_an_install_item_installed_less_than_a_day_ago_stays(self):
        self.receipt(MAIN)
        self.installed_item(ago_h=3)
        self.assertEqual(deskscan.tidy(), [])

    def test_a_waiting_install_item_is_never_tidied(self):
        self.receipt(OLD)
        deskfile.put_item("install:sheafmd", deskinstall.item_block(
            deskinstall.Tool("sheafmd", "sheafmd", REPO, OLD), MAIN, 3, "2026-11-12 10:00"), section="install")
        self.log_at("ready", "install:sheafmd", 500, pinned=MAIN)
        self.assertEqual(deskscan.tidy(), [])


if __name__ == "__main__":
    unittest.main()
