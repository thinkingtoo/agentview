"""The merge desk's hand-over: `desk ready`, `status`, `withdraw` through the command a session runs
and the page file they edit.

The command runs as a process of its own with `XDG_STATE_HOME` under a throwaway directory and a fake
`gh` first on PATH (a script that answers `pr view` from a file): never the real GitHub, never the real
state folder.
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
import deskfile

COMMAND = ROOT / "hooks" / "desk"
SHA = "ead9a1f" + "0" * 33
SHA2 = "b" * 40

FAKE_GH = f"""#!{sys.executable}
# fake gh: `gh pr view N -R repo --json ...` answers from $FAKE_GH_DIR/<repo with / as _>#<N>.json;
# `gh api repos/R/contents/.github/workflows[/f]` from the folder wf-<repo>, `gh api repos/R/compare/..` from compare-<repo>
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
if args[0] == "api":
    path = next(a for a in args if a.startswith("repos/"))
    repo_ = "_".join(path.split("/")[1:3])
    if "/contents/.github/workflows" in path:
        wf = d + "/wf-" + repo_
        name = path.split("/workflows")[1].split("?")[0].lstrip("/")
        if os.path.exists(d + "/api-fails"):
            print("gh: HTTP 502", file=sys.stderr)
            sys.exit(1)
        if not os.path.isdir(wf) or (name and not os.path.exists(wf + "/" + name)):
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            sys.exit(1)
        print(json.dumps([{{"name": n, "type": "file"}} for n in sorted(os.listdir(wf))]) if not name else open(wf + "/" + name).read())
        sys.exit(0)
    if "/compare/" in path:
        f = d + "/compare-" + repo_
        print(open(f).read() if os.path.exists(f) else json.dumps({{"total_commits": 0, "files": [], "commits": []}}))
        sys.exit(0)
if args[:2] != ["pr", "view"]:
    print("fake gh: unexpected " + " ".join(args), file=sys.stderr)
    sys.exit(9)
f = d + "/" + args[4].replace("/", "_") + "#" + args[2] + ".json"
if not os.path.exists(f):
    print("GraphQL: Could not resolve to a PullRequest", file=sys.stderr)
    sys.exit(1)
print(open(f).read())
"""


def setUpModule():
    # Sheaf's own lock for the file lives in the runtime folder: never the real one.
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
        self.state = self.tmp / "state"
        self.gh = self.tmp / "bin" / "gh"
        self.gh.parent.mkdir()
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IXUSR)
        self.prs = self.tmp / "prs"
        self.prs.mkdir()
        self.page = self.state / "agentview" / "merge-desk.md"

    def pr(self, repo, n, state="OPEN", head=SHA, base="dev"):
        (self.prs / f"{repo.replace('/', '_')}#{n}.json").write_text(
            json.dumps({"state": state, "headRefOid": head, "baseRefName": base}))

    def run_desk(self, *args):
        return subprocess.run(
            [sys.executable, str(COMMAND), *map(str, args)], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "XDG_STATE_HOME": str(self.state),
                 "XDG_RUNTIME_DIR": _runtime, "PATH": f"{self.gh.parent}:{os.environ['PATH']}", "FAKE_GH_DIR": str(self.prs)})

    def ready(self, n=272, repo="sweatshop-ai/sheaf", what="the dictation time limit", rec="merge", *more):
        return self.run_desk("ready", repo, n, "--what", what, "--rec", rec, "--why", "CI green", *more)

    def text(self):
        return self.page.read_text()


DEPLOY_YML = "name: deploy\non:\n  push:\n    branches: [dev]\njobs:\n  d:\n    runs-on: x\n    steps:\n      - run: ./deploy.sh\n"
TEST_YML = DEPLOY_YML.replace("./deploy.sh", "pytest").replace("name: deploy", "name: ci").replace("  d:", "  t:")


class Ships(Case):
    REPO = "tiroir/apex"

    def setUp(self):
        super().setUp()
        self.pr(self.REPO, 5)
        (self.prs / "compare-tiroir_apex").write_text(json.dumps({"total_commits": 1, "files": [], "commits": [
            {"sha": "abc1234" + "0" * 33, "commit": {"message": "Fix the thing\n\nbody"}}]}))

    def workflow(self, name, text):
        d = self.prs / "wf-tiroir_apex"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)

    def test_a_repo_whose_base_deploys_is_handed_over_as_a_deploy_item_with_what_ships(self):
        self.workflow("deploy.yml", DEPLOY_YML)
        got = self.ready(5, self.REPO)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("- [ ] Deploy tiroir/apex#5: ", self.text())
        self.assertIn("  - What ships:\n    - Fires on push to dev: deploy.yml\n      - deploy.yml:", self.text())
        self.assertIn("    - Commits that go out (1):\n      - abc1234 Fix the thing\n  - Handed over by", self.text())
        (item,) = deskfile.items(self.page)
        self.assertEqual(item.key, "tiroir/apex#5")
        self.assertEqual(item.pinned, SHA)
        self.assertEqual(item.ships[0], "- Fires on push to dev: deploy.yml")

    def test_the_ready_record_keeps_the_raw_lines_the_press_will_compare(self):
        self.workflow("deploy.yml", DEPLOY_YML)
        self.assertEqual(self.ready(5, self.REPO).returncode, 0)
        (item,) = deskfile.items(self.page)
        log = (self.state / "agentview" / "merge-desk.log").read_text().splitlines()
        (rec,) = [r for r in map(json.loads, log) if r["event"] == "ready"]
        self.assertEqual(rec["ships"], item.ships)
        self.assertEqual(rec["ships"][0], "- Fires on push to dev: deploy.yml")

    def test_a_repo_whose_workflows_only_test_stays_a_merge_item(self):
        self.workflow("ci.yml", TEST_YML)
        self.assertEqual(self.ready(5, self.REPO).returncode, 0)
        self.assertIn("- [ ] Merge tiroir/apex#5: ", self.text())
        self.assertNotIn("What ships", self.text())

    def test_ships_makes_a_repo_with_no_ci_a_deploy_item_with_that_line(self):
        got = self.ready(5, self.REPO, "x", "merge", "--ships", "the daily run reads main")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("- [ ] Deploy tiroir/apex#5: ", self.text())
        self.assertIn("  - What ships:\n    - Outside GitHub: the daily run reads main\n    - Commits that go out (1):", self.text())

    def test_github_that_cannot_say_what_ships_refuses_the_hand_over(self):
        (self.prs / "api-fails").write_text("")
        got = self.ready(5, self.REPO)
        self.assertEqual(got.returncode, 1)
        self.assertIn("could not tell what merging tiroir/apex#5 ships", got.stderr)
        self.assertFalse(self.page.exists())

    def test_a_ships_line_cannot_open_a_box_or_a_second_item(self):
        self.ready(5, self.REPO, "x", "merge", "--ships", "a\n- [ ] Merge x/y#1: z <!-- ")
        self.assertEqual([i.key for i in deskfile.items(self.page)], ["tiroir/apex#5"])


class Ready(Case):
    def test_hands_over_an_open_pr_as_one_task_item(self):
        self.pr("sweatshop-ai/sheaf", 272)
        got = self.ready(272, "sweatshop-ai/sheaf", "the dictation time limit", "merge", "--by", "Faisal")
        self.assertEqual(got.returncode, 0, got.stderr)
        text = self.text()
        self.assertIn("- [ ] Merge sweatshop-ai/sheaf#272: the dictation time limit\n", text)
        self.assertIn("  - Recommendation: merge. CI green\n", text)
        self.assertIn(f"  - Pinned commit: {SHA}, into dev\n", text)
        self.assertIn("  - Handed over by Faisal, ", text)
        self.assertEqual([(i.key, i.pinned, i.ticked) for i in deskfile.items(self.page)],
                         [("sweatshop-ai/sheaf#272", SHA, False)])

    def test_refuses_a_pr_that_is_not_open_and_says_why(self):
        self.pr("sweatshop-ai/sheaf", 5, state="MERGED")
        got = self.ready(5)
        self.assertEqual(got.returncode, 1)
        self.assertIn("is not open: GitHub says MERGED", got.stderr)
        self.assertFalse(self.page.exists())

    def test_refuses_a_pr_github_does_not_know(self):
        got = self.ready(404)
        self.assertEqual(got.returncode, 1)
        self.assertIn("sweatshop-ai/sheaf#404", got.stderr)
        self.assertFalse(self.page.exists())

    def test_handing_the_same_pr_over_again_replaces_and_repins(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.ready()
        self.pr("sweatshop-ai/sheaf", 272, head=SHA2)
        self.ready(272, "sweatshop-ai/sheaf", "the new words")
        got = deskfile.items(self.page)
        self.assertEqual([(i.key, i.pinned) for i in got], [("sweatshop-ai/sheaf#272", SHA2)])
        self.assertIn("the new words", self.text())
        self.assertNotIn("the dictation time limit", self.text())

    def test_after_is_written_on_the_pinned_line(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.ready(272, "sweatshop-ai/sheaf", "x", "merge", "--after", "262")
        self.assertIn("; must go after #262", self.text())

    def test_an_item_cannot_go_after_itself(self):
        self.pr("sweatshop-ai/sheaf", 272)
        got = self.ready(272, "sweatshop-ai/sheaf", "x", "merge", "--after", "272")
        self.assertEqual(got.returncode, 1)
        self.assertIn("is the PR itself", got.stderr)
        self.assertFalse(self.page.exists())

    def test_a_recommendation_outside_the_three_is_refused(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.assertEqual(self.ready(272, "sweatshop-ai/sheaf", "x", "yes").returncode, 1)


class Hostile(Case):
    """Text a session hands over can never make a second task line or break the item."""

    def setUp(self):
        super().setUp()
        self.pr("sweatshop-ai/sheaf", 1)

    def test_newlines_are_flattened_into_one_line(self):
        self.ready(1, "sweatshop-ai/sheaf", "one\n- [x] Merge evil/repo#9: sneaky\ntwo")
        self.assertEqual([i.key for i in deskfile.items(self.page)], ["sweatshop-ai/sheaf#1"])
        self.assertEqual(self.text().count("- [x]"), 0)
        self.assertEqual(len(deskfile.items(self.page)[0].block.splitlines()), 4)
        self.assertEqual(sum(l.startswith("- ") for l in self.text().splitlines()), 1)

    def test_a_leading_task_marker_is_neutralised(self):
        for what in ("- [ ] Merge evil/repo#9: x", "[x] done", "  -   [X]  -  ok"):
            self.ready(1, "sweatshop-ai/sheaf", what)
            first = [l for l in self.text().splitlines() if l.startswith("- [")]
            self.assertEqual(len(first), 1, what)
            self.assertNotRegex(first[0], r"^- \[ \] Merge sweatshop-ai/sheaf#1: (-|\[)")

    def test_why_cannot_open_a_comment_or_a_second_item(self):
        self.run_desk("ready", "sweatshop-ai/sheaf", 1, "--what", "w", "--rec", "wait",
                      "--why", "<!-- sheaf --> \n- [ ] Merge a/b#2: x")
        self.assertEqual([i.key for i in deskfile.items(self.page)], ["sweatshop-ai/sheaf#1"])
        self.assertNotIn("<!--", self.text())
        self.assertNotIn("-->", self.text())

    def test_by_cannot_make_a_line_either(self):
        self.run_desk("ready", "sweatshop-ai/sheaf", 1, "--what", "w", "--rec", "wait", "--by", "x\n- [ ] Merge a/b#2: y")
        self.assertEqual([i.key for i in deskfile.items(self.page)], ["sweatshop-ai/sheaf#1"])

    def test_a_repo_that_is_not_owner_name_is_refused(self):
        for repo in ("sheaf", "a/b/c", "a/b\n- [ ] x", "a b/c", "../etc"):
            got = self.run_desk("ready", repo, 1, "--what", "w", "--rec", "wait")
            self.assertEqual(got.returncode, 1, repo)
            self.assertIn("is not owner/name", got.stderr)
        self.assertFalse(self.page.exists())

    def test_a_number_that_is_not_a_number_is_refused(self):
        got = self.run_desk("ready", "a/b", "1;rm", "--what", "w", "--rec", "wait")
        self.assertEqual(got.returncode, 1)


class OneItemAtATime(Case):
    """A comment on another item survives an add, a replace and a withdraw."""
    COMMENT = "<!-- comment c1 by Thierry: please wait on this one -->"

    def setUp(self):
        super().setUp()
        self.pr("sweatshop-ai/sheaf", 1)
        self.pr("sweatshop-ai/sheaf", 2)
        self.pr("sweatshop-ai/sheaf", 3)
        self.ready(1)
        self.ready(2)
        # The person comments on item 2 and ticks nothing; the comment is in the file itself.
        t = self.text().replace("  - Recommendation: merge. CI green\n  - Pinned commit: " + SHA + ", into dev\n  - Handed over by a session",
                                "  - Recommendation: merge. CI green " + self.COMMENT + "\n  - Pinned commit: " + SHA + ", into dev\n  - Handed over by a session", 2)
        # (only the second occurrence, item 2, carries it)
        first = t.index(self.COMMENT)
        t = t[:first] + t[first:].replace(self.COMMENT, "", 1) if t.count(self.COMMENT) == 2 else t
        self.page.write_text(t)
        self.assertEqual(self.text().count(self.COMMENT), 1)
        self.item2 = self.block("sweatshop-ai/sheaf#2")

    def block(self, key):
        return next(i.block for i in deskfile.items(self.page) if i.key == key)

    def test_add(self):
        self.ready(3)
        self.assertEqual(self.block("sweatshop-ai/sheaf#2"), self.item2)
        self.assertEqual(self.text().count(self.COMMENT), 1)

    def test_replace_a_neighbour(self):
        self.ready(1, "sweatshop-ai/sheaf", "different words")
        self.assertEqual(self.block("sweatshop-ai/sheaf#2"), self.item2)
        self.assertIn("different words", self.text())

    def test_withdraw_a_neighbour(self):
        got = self.run_desk("withdraw", "sweatshop-ai/sheaf", 1)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual([i.key for i in deskfile.items(self.page)], ["sweatshop-ai/sheaf#2"])
        self.assertEqual(self.block("sweatshop-ai/sheaf#2"), self.item2)

    def test_a_tick_on_another_item_survives(self):
        t = self.text().replace("- [ ] Merge sweatshop-ai/sheaf#2", "- [x] Merge sweatshop-ai/sheaf#2")
        self.page.write_text(t)
        self.ready(3)
        got = {i.key: i.ticked for i in deskfile.items(self.page)}
        self.assertEqual(got, {"sweatshop-ai/sheaf#1": False, "sweatshop-ai/sheaf#2": True, "sweatshop-ai/sheaf#3": False})

    def test_withdrawing_what_is_not_there_is_refused_and_changes_nothing(self):
        before = self.text()
        got = self.run_desk("withdraw", "sweatshop-ai/sheaf", 9)
        self.assertEqual(got.returncode, 1)
        self.assertEqual(self.text(), before)

    def test_the_heading_text_around_the_items_is_kept(self):
        self.page.write_text(self.text() + "\n## Local installs waiting for you\n\n- [ ] Install sheaf: x\n  - old\n")
        self.ready(3)
        self.assertIn("- [ ] Install sheaf: x\n  - old\n", self.text())
        self.assertEqual([i.key for i in deskfile.items(self.page)][-1], "install:sheaf")
        self.assertLess(self.text().index("sheaf#3"), self.text().index("## Local installs"))


class Status(Case):
    def log(self, *recs):
        p = self.state / "agentview" / "merge-desk.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

    def test_waiting_after_a_hand_over(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.ready()
        got = self.run_desk("status", "sweatshop-ai/sheaf", 272)
        self.assertIn("sweatshop-ai/sheaf#272: waiting (pinned ead9a1f", got.stdout)

    def test_merged_as_a_sha_from_the_log(self):
        self.log({"at": "t1", "event": "ready", "key": "a/b#1", "pinned": SHA},
                 {"at": "t2", "event": "merged", "key": "a/b#1", "sha": "41678e3" + "0" * 33})
        self.assertIn("a/b#1: merged as 41678e3 at t2", self.run_desk("status", "a/b", 1).stdout)

    def test_refused_and_why(self):
        self.log({"at": "t1", "event": "ready", "key": "a/b#1", "pinned": SHA},
                 {"at": "t2", "event": "refused", "key": "a/b#1", "why": "the branch changed after the review"})
        self.assertIn("a/b#1: refused: the branch changed after the review", self.run_desk("status", "a/b", 1).stdout)

    def test_a_new_hand_over_after_a_refusal_waits_again(self):
        self.log({"at": "t1", "event": "refused", "key": "a/b#1", "why": "x"},
                 {"at": "t2", "event": "ready", "key": "a/b#1", "pinned": SHA})
        self.assertIn("waiting", self.run_desk("status", "a/b", 1).stdout)

    def test_withdrawn_and_unknown(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.ready()
        self.run_desk("withdraw", "sweatshop-ai/sheaf", 272)
        self.assertIn("withdrawn", self.run_desk("status", "sweatshop-ai/sheaf", 272).stdout)
        self.assertIn("not on the desk", self.run_desk("status", "x/y", 1).stdout)

    def test_status_alone_lists_every_item_with_history(self):
        self.log({"at": "t1", "event": "ready", "key": "a/b#1", "pinned": SHA},
                 {"at": "t1", "event": "ready", "key": "a/b#2", "pinned": SHA})
        out = self.run_desk("status").stdout
        self.assertIn("a/b#1: waiting", out)
        self.assertIn("a/b#2: waiting", out)


class Place(Case):
    def test_state_is_under_xdg_state_home_only(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.ready()
        made = {p.relative_to(self.state).as_posix() for p in self.state.rglob("*") if p.is_file()}
        self.assertEqual(made, {"agentview/merge-desk.md", "agentview/merge-desk.log", "agentview/.merge-desk.lock"})

    def test_gh_is_resolved_to_an_absolute_path_once(self):
        import desk
        self.assertTrue(desk.GH is None or os.path.isabs(desk.GH))


class RehandOver(unittest.TestCase):
    """A second hand-over of an item already on the page replaces the lines AgentView wrote and keeps the rest:
    sheaf's comment threads, and what the person wrote."""

    OLD_SHA, NEW_SHA = "a" * 40, "b" * 40
    THREAD = ('<!-- sheaf-comment id=c1 by="Thierry" at=2026-11-14T01:00 status=open quote="Merge it."\n'
              'Wait for Friday, the client is away.\n'
              '@Claude 2026-11-14T01:05 answer: Noted.\n'
              '-->')

    def block(self, sha, rec="Merge it.", when="01:00"):
        return (f"- [ ] Merge a/b#1: what it does\n  - Recommendation: {rec}\n  - Pinned commit: {sha}, into main\n"
                f"  - Handed over by a session, 2026-11-14 {when}.\n")

    def page(self, body):
        return "# D\n\n## Pull requests waiting for your merge\n" + body + "- [ ] Merge a/b#2: next\n"

    def test_an_open_thread_survives_a_new_hand_over_word_for_word(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA, when="02:00"))
        self.assertIn(self.THREAD, got)
        self.assertEqual(got.count("sheaf-comment"), 1)
        self.assertEqual([i.key for i in deskfile.parse(got)], ["a/b#1", "a/b#2"])

    def test_the_items_own_lines_are_the_new_ones(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA, rec="Wait.", when="02:00"))
        it = deskfile.parse(got)[0]
        self.assertEqual(it.pinned, self.NEW_SHA)
        self.assertNotIn(self.OLD_SHA, got)
        self.assertNotIn("01:00.", got)
        self.assertIn("02:00.", got)
        self.assertIn("Recommendation: Wait.", got)
        self.assertIn(self.THREAD, got)

    def test_a_thread_on_the_task_line_and_on_the_pinned_line_both_stay(self):
        t1 = self.THREAD.replace("c1", "c1")
        t2 = self.THREAD.replace("id=c1", "id=c2").replace("Friday", "Monday")
        old = self.block(self.OLD_SHA)
        old = old.replace("what it does\n", "what it does" + t1 + "\n", 1).replace(", into main\n", ", into main" + t2 + "\n", 1)
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn(t1, got)
        self.assertIn(t2, got)

    def test_a_thread_on_a_line_the_new_block_no_longer_has_stays_on_the_item(self):
        old = self.block(self.OLD_SHA).replace("2026-11-14 01:00.\n", "2026-11-14 01:00." + self.THREAD + "\n", 1)
        old = old.replace("  - Handed over", "  - What ships:\n    - the server" + self.THREAD.replace("id=c1", "id=c9") + "\n  - Handed over")
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))     # a block with no What ships
        self.assertIn(self.THREAD, got)
        self.assertIn(self.THREAD.replace("id=c1", "id=c9"), got)
        self.assertNotIn("the server", got.replace(self.THREAD.replace("id=c1", "id=c9"), ""))
        self.assertEqual([i.key for i in deskfile.parse(got)], ["a/b#1", "a/b#2"])

    def test_a_line_the_person_wrote_in_the_item_stays(self):
        old = self.block(self.OLD_SHA) + "  - Friday is fine for me, not before.\n"
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn("  - Friday is fine for me, not before.\n", got)
        self.assertEqual(got.count("Friday is fine"), 1)

    def test_the_same_hand_over_twice_changes_nothing_the_second_time(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)
        once = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertEqual(deskfile.put(once, "a/b#1", self.block(self.NEW_SHA)), once)

    def test_a_result_line_of_an_earlier_press_is_replaced_not_kept(self):
        old = self.block(self.OLD_SHA) + "  - Not merged: CI is red\n"
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertNotIn("Not merged", got)

    def test_what_ships_lines_are_the_new_ones(self):
        old = self.block(self.OLD_SHA).replace("  - Handed", "  - What ships:\n    - old thing\n  - Handed", 1)
        new = self.block(self.NEW_SHA).replace("  - Handed", "  - What ships:\n    - new thing\n  - Handed", 1)
        got = deskfile.put(self.page(old), "a/b#1", new)
        self.assertIn("new thing", got)
        self.assertNotIn("old thing", got)

    def test_a_thread_on_an_install_item_stays_when_the_scan_re_pins_it(self):
        def blk(sha):
            return (f"- [ ] Install sheaf: o/sheaf is 2 commits behind main\n  - Recommendation: found by the scan, no recommendation yet.\n"
                    f"  - Pinned commit: {sha}, main of o/sheaf; installed now: {'c' * 40}\n  - Handed over by AgentView's scan, 2026-11-14 01:00.\n")
        old = blk(self.OLD_SHA).replace("recommendation yet.\n", "recommendation yet." + self.THREAD + "\n", 1)
        text = "# D\n\n## Local installs waiting for you\n" + old
        got = deskfile.put(text, "install:sheaf", blk(self.NEW_SHA), section="install")
        self.assertIn(self.THREAD, got)
        self.assertEqual(deskfile.parse(got)[0].pinned, self.NEW_SHA)

    def test_a_thread_whose_closing_arrow_was_lost_is_kept_too(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it.<!-- sheaf-comment id=c1 by=\"T\" at=2026-11-14T01:00 status=open quote=\"x\"\nhalf a thread\n", 1)
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn("half a thread", got)


class Comments(unittest.TestCase):
    """Sheaf keeps the person's comments inside the file; their text is never structure."""

    def test_a_list_line_in_a_comment_does_not_end_the_item(self):
        text = ("## Pull requests waiting for your merge\n"
                "- [ ] Merge a/b#1: first\n  - Pinned commit: " + "a" * 40 + "\n"
                "<!-- comment:\n- do not merge until Friday\n## Pull requests waiting for your merge\n-->\n"
                "- [ ] Merge a/b#2: second\n")
        self.assertEqual(deskfile.drop(text, "a/b#1"), "## Pull requests waiting for your merge\n- [ ] Merge a/b#2: second\n")
        replaced = deskfile.put(text, "a/b#1", "- [ ] Merge a/b#1: new\n")
        self.assertNotIn("do not merge", replaced)
        self.assertEqual([i.key for i in deskfile.parse(replaced)], ["a/b#1", "a/b#2"])

    def test_a_heading_named_in_a_comment_is_not_the_section(self):
        text = ("# Desk\n\n<!-- Thierry mentioned ## Pull requests waiting for your merge here -->\n"
                "## Pull requests waiting for your merge\n")
        got = deskfile.put(text, "a/b#1", "- [ ] Merge a/b#1: x\n")
        self.assertGreater(got.index("- [ ] Merge a/b#1"), got.index("-->"))
        self.assertEqual([i.key for i in deskfile.parse(got)], ["a/b#1"])

    def test_a_log_record_without_event_or_key_is_skipped(self):
        import desk
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "agentview").mkdir()
        (tmp / "agentview" / "merge-desk.log").write_text(
            json.dumps({"at": "t1", "event": "ready", "key": "a/b#1", "pinned": SHA}) + "\n"
            + json.dumps({"at": "t2", "key": "a/b#1"}) + "\n" + json.dumps({"event": "ready"}) + "\n")
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(tmp)
        self.addCleanup(lambda: os.environ.pop("XDG_STATE_HOME") if old is None else os.environ.update(XDG_STATE_HOME=old))
        self.assertIn("waiting", desk.status_line("a/b#1"))
        self.assertEqual(len(desk.status_all()), 1)

    def test_a_record_without_a_time_still_reads(self):
        import desk
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "agentview").mkdir()
        (tmp / "agentview" / "merge-desk.log").write_text(json.dumps({"event": "ready", "key": "a/b#1"}) + "\n")
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(tmp)
        self.addCleanup(lambda: os.environ.pop("XDG_STATE_HOME") if old is None else os.environ.update(XDG_STATE_HOME=old))
        self.assertIn("a/b#1: waiting", desk.status_line("a/b#1"))

    def test_a_pinned_line_in_a_comment_pins_nothing(self):
        text = ("- [x] Merge a/b#1: r\n  <!--\n  - Pinned commit: " + "a" * 40 + "\n  -->\n  - Pinned commit: " + "b" * 40 + "\n")
        self.assertEqual(deskfile.parse(text)[0].pinned, "b" * 40)

    def test_a_heading_at_the_end_without_a_newline_is_the_section(self):
        got = deskfile.put("# D\n## Pull requests waiting for your merge", "a/b#1", "- [ ] Merge a/b#1: x\n")
        self.assertEqual(got.count("## Pull requests waiting"), 1)
        self.assertEqual([i.key for i in deskfile.parse(got)], ["a/b#1"])

    def test_the_writer_takes_sheafs_own_lock_too(self):
        import fcntl
        f = Path(tempfile.mkdtemp()) / "merge-desk.md"
        self.addCleanup(shutil.rmtree, f.parent, True)
        lock = deskfile.sheaf_lock_path(f)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)           # sheaf is writing
            import threading, time
            done = []
            t = threading.Thread(target=lambda: (deskfile.put_item("o/r#1", "- [ ] Merge o/r#1: w\n", file=f), done.append(1)))
            t.start(); time.sleep(0.5)
            self.assertEqual(done, [])               # we wait for it
            fcntl.flock(fh, fcntl.LOCK_UN)
        t.join(5)
        self.assertEqual(done, [1])

    def test_a_write_by_another_writer_between_read_and_replace_is_not_lost(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        f = tmp / "merge-desk.md"
        deskfile.put_item("o/r#1", "- [ ] Merge o/r#1: w\n", file=f)
        calls = []

        def change(text):
            calls.append(1)
            if len(calls) == 1:        # sheaf ticks the box while we compute
                f.write_text(text.replace("- [ ]", "- [x]"))
            return deskfile.put(text, "o/r#2", "- [ ] Merge o/r#2: w\n")
        deskfile.edit(change, file=f)
        got = {i.key: i.ticked for i in deskfile.items(f)}
        self.assertEqual(got, {"o/r#1": True, "o/r#2": False})


class Lock(unittest.TestCase):
    def test_two_edits_at_once_lose_neither(self):
        import threading
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        f = tmp / "merge-desk.md"
        def add(i):
            deskfile.put_item(f"o/r#{i}", f"- [ ] Merge o/r#{i}: w\n", file=f)
        ts = [threading.Thread(target=add, args=(i,)) for i in range(1, 21)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(i.key for i in deskfile.items(f)), sorted(f"o/r#{i}" for i in range(1, 21)))


if __name__ == "__main__":
    unittest.main()
