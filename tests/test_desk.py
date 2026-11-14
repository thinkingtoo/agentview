"""The merge desk's hand-over: `desk ready`, `status`, `withdraw` through the command a session runs
and the page file they edit.

The command runs as a process of its own with `XDG_STATE_HOME` under a throwaway directory and a fake
`gh` first on PATH (a script that answers `pr view` from a file): never the real GitHub, never the real
state folder.
"""
import contextlib
import copy
import json
from collections import Counter
from unittest import mock
import os
import re
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



def written(text):
    """The record of a page AgentView is taken to have written whole: for each item, the lines of its block."""
    return {deskfile._slot(k): {"lines": deskfile._heads(text[s:e]), "prev": []} for k, s, e in deskfile._spans(text)}


def put_after(text, key, block, ours=None, **kw):
    """`deskfile.put` on a page AgentView wrote (it has a record of it). `ours`: the page as AgentView wrote it, when the person has typed into `text` since."""
    return deskfile.put(text, key, block, record=written(text if ours is None else ours), **kw)


def parse_after(text):
    return deskfile.parse(text, written(text))

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


class Adopt(Case):
    def test_desk_adopt_takes_a_legacy_page_once_and_says_so(self):
        self.pr("sweatshop-ai/sheaf", 272)
        self.assertEqual(self.ready().returncode, 0)
        (self.page.parent / ".merge-desk.own.json").unlink()
        first = self.run_desk("adopt")
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "adopted: sweatshop-ai/sheaf#272"))
        second = self.run_desk("adopt")
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "adopted: nothing, every item has a record"))


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
        self.assertEqual(made, {"agentview/merge-desk.md", "agentview/merge-desk.log", "agentview/.merge-desk.lock",
                                "agentview/.merge-desk.own.json"})

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
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA, when="02:00"))
        self.assertIn(self.THREAD, got)
        self.assertEqual(got.count("sheaf-comment"), 1)
        self.assertEqual([i.key for i in parse_after(got)], ["a/b#1", "a/b#2"])

    ORPHAN = THREAD.replace("status=open ", "status=open orphan=1 ")

    def test_the_items_own_lines_are_the_new_ones(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA, rec="Wait.", when="02:00"))
        it = parse_after(got)[0]
        self.assertEqual(it.pinned, self.NEW_SHA)
        self.assertNotIn(self.OLD_SHA, got)
        self.assertNotIn("01:00.", got)
        self.assertIn("02:00.", got)
        self.assertIn("Recommendation: Wait.", got)
        self.assertIn(self.ORPHAN, got)                 # the words it quoted are gone from the line

    def test_a_thread_on_the_task_line_and_on_the_pinned_line_both_stay(self):
        t1 = self.THREAD.replace('quote="Merge it."', 'quote="what it does"')
        t2 = self.THREAD.replace("id=c1", "id=c2").replace("Friday", "Monday").replace('quote="Merge it."', 'quote="into main"')
        old = self.block(self.OLD_SHA)
        old = old.replace("what it does\n", "what it does" + t1 + "\n", 1).replace(", into main\n", ", into main" + t2 + "\n", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn(t1, got)
        self.assertIn(t2, got)

    def test_a_thread_on_a_line_the_new_block_no_longer_has_stays_on_the_item(self):
        old = self.block(self.OLD_SHA).replace("2026-11-14 01:00.\n", "2026-11-14 01:00." + self.THREAD + "\n", 1)
        old = old.replace("  - Handed over", "  - What ships:\n    - the server" + self.THREAD.replace("id=c1", "id=c9") + "\n  - Handed over")
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))     # a block with no What ships
        self.assertIn(self.THREAD, got)                                                 # its line is the same: the thread stays on it
        self.assertIn(self.ORPHAN.replace("id=c1", "id=c9"), got)                       # its line is gone
        self.assertNotIn("the server", got.replace(self.ORPHAN.replace("id=c1", "id=c9"), ""))
        self.assertEqual([i.key for i in parse_after(got)], ["a/b#1", "a/b#2"])

    def test_a_line_the_person_wrote_in_the_item_stays(self):
        old = self.block(self.OLD_SHA) + "  - Friday is fine for me, not before.\n"
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA), ours=self.page(self.block(self.OLD_SHA)))
        self.assertIn("  - Friday is fine for me, not before.\n", got)
        self.assertEqual(got.count("Friday is fine"), 1)

    def test_the_same_hand_over_twice_changes_nothing_the_second_time(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)
        once = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertEqual(put_after(once, "a/b#1", self.block(self.NEW_SHA)), once)

    def test_a_result_line_of_an_earlier_press_is_replaced_not_kept(self):
        old = self.block(self.OLD_SHA) + "  - Not merged: CI is red\n"
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertNotIn("Not merged", got)

    def test_what_ships_lines_are_the_new_ones(self):
        old = self.block(self.OLD_SHA).replace("  - Handed", "  - What ships:\n    - old thing\n  - Handed", 1)
        new = self.block(self.NEW_SHA).replace("  - Handed", "  - What ships:\n    - new thing\n  - Handed", 1)
        got = put_after(self.page(old), "a/b#1", new)
        self.assertIn("new thing", got)
        self.assertNotIn("old thing", got)

    def test_a_thread_on_an_install_item_stays_when_the_scan_re_pins_it(self):
        def blk(sha):
            return (f"- [ ] Install sheaf: o/sheaf is 2 commits behind main\n  - Recommendation: found by the scan, no recommendation yet.\n"
                    f"  - Pinned commit: {sha}, main of o/sheaf; installed now: {'c' * 40}\n  - Handed over by AgentView's scan, 2026-11-14 01:00.\n")
        old = blk(self.OLD_SHA).replace("recommendation yet.\n", "recommendation yet." + self.THREAD + "\n", 1)
        text = "# D\n\n## Local installs waiting for you\n" + old
        got = put_after(text, "install:sheaf", blk(self.NEW_SHA), section="install")
        self.assertIn(self.THREAD, got)
        self.assertEqual(parse_after(got)[0].pinned, self.NEW_SHA)

    def test_text_after_a_threads_closing_arrow_stays(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + " PERSON: only after Friday\n", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA), ours=self.page(self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it." + self.THREAD + "\n", 1)))
        self.assertIn(self.THREAD + "\n  PERSON: only after Friday\n", got)      # the words after the arrow are the person's line, kept whole

    def test_a_thread_on_a_line_of_its_own_stays_where_it_stood(self):
        old = self.block(self.OLD_SHA).replace("  - Pinned", "  " + self.THREAD + "\n  - Pinned", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn("  " + self.THREAD + "\n  - Pinned commit: " + self.NEW_SHA, got)
        self.assertEqual(put_after(got, "a/b#1", self.block(self.NEW_SHA)), got)

    def test_a_person_line_shaped_like_ours_but_not_exactly_stays_and_keeps_its_place(self):
        old = (self.block(self.OLD_SHA) + "  - Recommendation: PERSON: do not merge yet\n    because the migration is tomorrow\n"
               + "  - Pinned commit: see the thread above\n")
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA), ours=self.page(self.block(self.OLD_SHA)))
        self.assertIn("  - Recommendation: PERSON: do not merge yet\n    because the migration is tomorrow\n  - Pinned commit: see the thread above\n", got)
        self.assertEqual(put_after(got, "a/b#1", self.block(self.NEW_SHA), ours=self.page(self.block(self.NEW_SHA))), got)

    def test_a_thread_moved_to_the_end_is_still_there_after_a_second_hand_over(self):
        old = self.block(self.OLD_SHA).replace("  - Handed", "  - What ships:\n    - old deployment" + self.THREAD + "\n  - Handed", 1)
        once = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn(self.ORPHAN, once)
        self.assertEqual(put_after(once, "a/b#1", self.block(self.NEW_SHA)), once)

    def test_an_unclosed_thread_on_the_task_line_is_kept_and_hides_none_of_the_new_lines(self):
        old = self.block(self.OLD_SHA).replace("what it does\n", "what it does<!-- sheaf-comment id=c1 by=\"T\" at=2026-11-14T01:00 status=open quote=\"x\"\nunfinished thread\n", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn("unfinished thread", got)
        self.assertEqual(parse_after(got)[0].pinned, self.NEW_SHA)
        self.assertEqual(put_after(got, "a/b#1", self.block(self.NEW_SHA)), got)

    def test_the_text_after_an_unclosed_thread_to_the_end_of_the_file_is_kept(self):
        text = ("# D\n\n## Pull requests waiting for your merge\n- [ ] Merge a/b#1: first\n  - Recommendation: merge.<!-- sheaf-comment id=c1\n"
                "unfinished thread\n- [ ] Merge a/b#2: second\n  - PERSON'S TEXT\n")
        got = put_after(text, "a/b#1", "- [ ] Merge a/b#1: first\n  - Recommendation: wait.\n")
        for kept in ("unfinished thread", "Merge a/b#2: second", "PERSON'S TEXT"):
            self.assertIn(kept, got)

    def test_a_line_after_a_ships_bullet_that_changed_does_not_split_the_new_list(self):
        old = ("- [ ] Deploy a/b#1: x\n  - What ships:\n    - old deployment\n  <!-- do this after Friday -->\n  - Pinned commit: " + self.OLD_SHA + "\n"
               "  - Handed over by a session, 2026-11-14 01:00.\n")
        new = ("- [ ] Deploy a/b#1: x\n  - What ships:\n    - new deployment\n    - second\n  - Pinned commit: " + self.NEW_SHA + "\n"
               "  - Handed over by a session, 2026-11-14 02:00.\n")
        got = put_after(self.page(old), "a/b#1", new)
        self.assertIn("<!-- do this after Friday -->", got)
        self.assertEqual(parse_after(got)[0].ships, ["- new deployment", "- second"])
        self.assertEqual(put_after(got, "a/b#1", new), got)

    def test_a_thread_on_the_second_of_two_identical_bullets_stays_on_the_second(self):
        old = ("- [ ] Deploy a/b#1: x\n  - What ships:\n    - restart worker\n    - restart worker" + self.THREAD + "\n  - Pinned commit: " + self.OLD_SHA + "\n")
        new = old.replace(self.THREAD, "").replace(self.OLD_SHA, self.NEW_SHA)
        got = put_after(self.page(old), "a/b#1", new)
        self.assertEqual(got, self.page(old.replace(self.OLD_SHA, self.NEW_SHA)))
        self.assertEqual(put_after(got, "a/b#1", new), got)

    def test_a_thread_whose_closing_arrow_was_lost_is_kept_too(self):
        old = self.block(self.OLD_SHA).replace("Merge it.\n", "Merge it.<!-- sheaf-comment id=c1 by=\"T\" at=2026-11-14T01:00 status=open quote=\"x\"\nhalf a thread\n", 1)
        got = put_after(self.page(old), "a/b#1", self.block(self.NEW_SHA))
        self.assertIn("half a thread", got)


def squash(s):
    return "".join(s.split())


def anchor_problems(text):
    """Sheaf's anchor rule for a thread (SPEC 5.2, `edit._occurrence`): the passage it quotes is the words just before it,
    in the text its own line shows. A thread flagged `orphan=1` stands on a line of its own and says its text is gone.
    Returns the quotes of the threads that sit on a line whose words do not end with them."""
    import html
    import re
    bad = []
    for line in text.split("\n"):
        for m in re.finditer(r'<!-- sheaf-comment [^\n]*?(orphan=1 )?quote="([^"\n]*)"', line):
            if m.group(1):
                continue
            before = re.sub(r"<!--.*?-->", "", line[:m.start()])
            before = re.sub(r"^\s*(?:[-*+] (?:\[[ xX]\] )?)?", "", before)
            if not squash(before).endswith(squash(html.unescape(m.group(2)))):
                bad.append(m.group(2))
    return bad


class OwnRecord(unittest.TestCase):
    """AgentView keeps a record of the lines it wrote last, so a line is its own only when it is one of those:
    nothing the person wrote is ever taken for it, whatever shape it has."""

    OLD_SHA, NEW_SHA = "a" * 40, "b" * 40
    THREAD = ('<!-- sheaf-comment id=c1 by="Thierry" at=2026-11-14T01:00 status=open quote="QUOTE"\n'
              'Wait for Friday.\n'
              '-->')

    def thread(self, quote, cid="c1"):
        return self.THREAD.replace("QUOTE", quote).replace("id=c1", f"id={cid}")

    def block(self, sha, rec="Merge it.", when="01:00", ships=()):
        out = f"- [ ] Deploy a/b#1: what it does\n  - Recommendation: {rec}\n"
        if ships:
            out += "  - What ships:\n" + "".join(f"    - {b}\n" for b in ships)
        return out + f"  - Pinned commit: {sha}, into main\n  - Handed over by a session, 2026-11-14 {when}.\n"

    def page(self, body):
        return "# D\n\n## Pull requests waiting for your merge\n" + body + "- [ ] Merge a/b#2: next\n"

    def hand_over(self, text, block, rec):
        return deskfile.put(text, "a/b#1", block, record=rec)

    def test_a_note_of_the_persons_under_what_ships_survives_a_new_hand_over(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, ships=["restart worker", "run migration"]), rec)
        text = text.replace("    - run migration\n", "    - run migration\n    - NOTE: run it by hand, not by the script\n")
        got = self.hand_over(text, self.block(self.NEW_SHA, ships=["restart worker", "run migration 2"]), rec)
        self.assertIn("    - NOTE: run it by hand, not by the script\n", got)
        self.assertNotIn("run migration\n", got)
        self.assertIn("    - run migration 2\n", got)
        self.assertEqual(got.count("NOTE: run it by hand"), 1)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, ships=["restart worker", "run migration 2"]), rec), got)

    def test_a_ticked_box_is_not_a_change_of_the_task_line(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("- [ ] Deploy a/b#1", "- [x] Deploy a/b#1", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA).replace("what it does", "what it does now"), rec)
        self.assertIn("- [ ] Deploy a/b#1: what it does now\n", got)
        self.assertNotIn("[x]", got)
        self.assertEqual(got.count("Deploy a/b#1"), 1)

    def test_the_previous_pin_line_typed_by_the_person_pins_nothing(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = self.hand_over(text, self.block(self.NEW_SHA), rec)
        text = text.replace(f"  - Pinned commit: {self.NEW_SHA}", f"  - Pinned commit: {self.OLD_SHA}, into main\n  - Pinned commit: {self.NEW_SHA}", 1)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(text, rec)}["a/b#1"], self.NEW_SHA)

    def test_a_note_between_two_ships_bullets_does_not_turn_the_next_bullet_into_the_persons(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, ships=["one", "two"]), rec)
        text = text.replace("    - one\n", "    - one\n    - NOTE from the person\n")
        got = self.hand_over(text, self.block(self.NEW_SHA, ships=["uno", "due"]), rec)
        self.assertIn("NOTE from the person", got)
        self.assertNotIn("    - one\n", got)
        self.assertNotIn("    - two\n", got)
        self.assertEqual(got.count("    - uno\n") + got.count("    - due\n"), 2)

    def test_a_page_with_crlf_line_ends_has_its_lines_replaced_not_a_block_appended(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        crlf = text.replace("\n", "\r\n")
        got = self.hand_over(crlf, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        self.assertEqual((got.count("Recommendation"), got.count("Pinned commit"), got.count("Handed over")), (1, 1, 1))
        self.assertNotIn(self.OLD_SHA, got)

    def test_settle_on_an_item_with_no_record_replaces_the_earlier_result_line(self):
        rec = {}
        text = self.page(self.block(self.OLD_SHA))
        text = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        text = deskfile.settle(text, "a/b#1", "Not merged: CI is red again", record=rec)
        self.assertEqual(text.count("Not merged:"), 1)
        self.assertIn("Not merged: CI is red again", text)

    def test_a_new_item_on_a_crlf_page_goes_under_its_heading_and_a_second_refusal_replaces_the_first(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec).replace("\n", "\r\n")
        got = deskfile.put(text, "a/b#9", "- [ ] Merge a/b#9: new\n", record=rec)
        self.assertEqual(got.count("## Pull requests waiting for your merge"), 1)
        got = deskfile.settle(got, "a/b#1", "Not merged: CI is red", record=rec)
        got = deskfile.settle(got.replace("\n", "\r\n").replace("\r\r", "\r"), "a/b#1", "Not merged: again", record=rec)
        self.assertEqual(got.count("Not merged:"), 1)

    def test_a_page_two_generations_behind_its_record_is_still_replaced_whole(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)        # two writes that never reached the page
        self.hand_over(text, self.block("c" * 40, when="03:00"), rec)
        got = self.hand_over(text, self.block("d" * 40, when="04:00"), rec)
        self.assertEqual((got.count("Recommendation"), got.count("Pinned commit"), got.count("Handed over")), (1, 1, 1))

    def test_an_unterminated_comment_on_our_line_does_not_add_a_second_recommendation_and_closes_the_comment(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec) + "- [ ] Merge a/b#3: after\n"
        text = text.replace("Recommendation: Merge it.\n", "Recommendation: Merge it.<!-- never closed\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        self.assertEqual(got.count("Recommendation:"), 1)
        self.assertEqual([i.key for i in deskfile.parse(got, rec)], ["a/b#2", "a/b#1", "a/b#3"])      # a/b#3 was inside the open comment: it is an item again
        self.assertEqual(got.count("<!--"), got.count("-->"))                                  # the comment is closed, before it
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec), got)

    def test_a_person_line_shaped_like_a_recommendation_survives(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Pinned commit:", "  - Recommendation: wait, the client is away\n  - Pinned commit:", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Merge now."), rec)
        self.assertIn("  - Recommendation: wait, the client is away\n", got)
        self.assertIn("  - Recommendation: Merge now.\n", got)
        self.assertNotIn("Recommendation: Merge it.", got)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, rec="Merge now."), rec), got)

    def test_person_lines_shaped_like_the_pinned_line_the_handed_over_line_and_a_result_survive(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        mine = [f"  - Pinned commit: {'c' * 40}, my own note\n", "  - Handed over by me, 2026-11-14 03:00.\n", "  - Not merged: I decided so\n"]
        text += "".join(mine)                                                # the item is the last on the page
        got = self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        for line in mine:
            self.assertIn(line, got)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)      # the first pinned line is still the one that counts
        self.assertNotIn("01:00.", got)

    def test_a_person_line_shaped_like_the_pinned_line_above_ours_does_not_change_what_is_pinned(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Recommendation:", "  - Pinned commit: 1234567 (checked by me)\n  - Recommendation:", 1)
        pinned = lambda t: {i.key: (i.pinned, i.after) for i in deskfile.parse(t, record=rec)}["a/b#1"]
        self.assertEqual(pinned(text), (self.OLD_SHA, 0))
        got = self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertIn("  - Pinned commit: 1234567 (checked by me)\n", got)
        self.assertEqual(pinned(got), (self.NEW_SHA, 0))

    def test_a_pin_line_the_person_changed_in_place_pins_nothing_but_still_orders(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace(f"Pinned commit: {self.OLD_SHA}, into main", f"Pinned commit: {self.NEW_SHA}, into main; must go after #5", 1)
        item = {i.key: i for i in deskfile.parse(text, record=rec)}["a/b#1"]
        self.assertEqual((item.pinned, item.after), ("", 5))

    def test_the_pin_is_read_from_our_line_through_the_file_too(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
        self.addCleanup(lambda: os.environ.pop("XDG_RUNTIME_DIR") if old is None else os.environ.update(XDG_RUNTIME_DIR=old))
        f = tmp / "state" / "merge-desk.md"
        deskfile.put_item("a/b#1", self.block(self.OLD_SHA), file=f)
        f.write_text(f.read_text().replace("  - Recommendation:", "  - Pinned commit: 1234567 (mine)\n  - Recommendation:", 1))
        self.assertEqual(deskfile.items(f)[0].pinned, self.OLD_SHA)

    def test_words_after_a_thread_that_ends_our_line_become_the_persons_line_not_part_of_ours(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec="Merge it."), rec)
        text = text.replace("Merge it.", "Merge it." + self.thread("Merge it.") + " and fine", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Merge it now.", when="02:00"), rec)
        bare = re.sub(r"<!--.*?-->", "", got, flags=re.S)
        self.assertIn("  - Recommendation: Merge it now.\n", bare)
        self.assertIn("\n  and fine\n", bare)
        self.assertNotIn("Merge it now. and fine", bare)
        self.assertEqual(got.count("sheaf-comment"), 1)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, rec="Merge it now.", when="02:00"), rec), got)

    def test_an_item_with_no_record_keeps_every_line_whatever_its_shape(self):
        old = self.block(self.OLD_SHA) + "  - Not merged: CI is red\n"
        got = deskfile.put(self.page(old), "a/b#1", self.block(self.NEW_SHA), record={})
        self.assertIn("Not merged: CI is red", got)
        self.assertIn(self.OLD_SHA, got)
        self.assertIn(self.NEW_SHA, got)

    def test_a_press_result_is_part_of_the_record_and_is_replaced(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        got = self.hand_over(text, self.block(self.NEW_SHA), rec)
        self.assertNotIn("Not merged", got)

    def test_a_line_the_person_changed_in_place_is_theirs_from_then_on(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("Recommendation: Merge it.", "Recommendation: Merge it, after Friday.")
        got = self.hand_over(text, self.block(self.NEW_SHA), rec)
        self.assertIn("Recommendation: Merge it, after Friday.\n", got)

    def test_the_record_does_not_change_when_the_same_block_is_put_again(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        before = json.dumps(rec, sort_keys=True)
        self.hand_over(text, self.block(self.OLD_SHA), rec)
        self.assertEqual(json.dumps(rec, sort_keys=True), before)

    def test_a_dropped_item_leaves_no_record(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        deskfile.drop(text, "a/b#1", record=rec)
        self.assertEqual(rec, {})

    def test_the_record_is_kept_beside_the_file_by_edit(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
        self.addCleanup(lambda: os.environ.pop("XDG_RUNTIME_DIR") if old is None else os.environ.update(XDG_RUNTIME_DIR=old))
        f = tmp / "state" / "merge-desk.md"
        deskfile.put_item("a/b#1", self.block(self.OLD_SHA, ships=["one"]), file=f)
        f.write_text(f.read_text().replace("    - one\n", "    - one\n    - NOTE: mine\n"))
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, ships=["uno"]), file=f)
        got = f.read_text()
        self.assertIn("    - NOTE: mine\n", got)
        self.assertIn("    - uno\n", got)
        self.assertNotIn("    - one\n", got)
        deskfile.edit(lambda t: deskfile.settle(t, "a/b#1", "Not merged: CI is red"), f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, when="09:00", ships=["uno"]), file=f)
        self.assertNotIn("Not merged", f.read_text())
        self.assertIn("NOTE: mine", f.read_text())
        deskfile.drop_item("a/b#1", file=f)
        self.assertEqual(json.loads((tmp / "state" / ".merge-desk.own.json").read_text()), {})

    def test_a_thread_on_a_line_whose_words_changed_keeps_an_anchor_sheaf_finds(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("Merge it.\n", "Merge it." + self.thread("Merge it.") + "\n", 1)
        self.assertEqual(anchor_problems(text), [])
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Wait, the migration is tomorrow."), rec)
        self.assertEqual(anchor_problems(got), [])
        self.assertIn("orphan=1", got)
        self.assertIn("Wait for Friday.", got)
        self.assertEqual(got.count("sheaf-comment"), 1)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, rec="Wait, the migration is tomorrow."), rec), got)

    def test_a_thread_quoting_words_the_line_shows_without_their_marks_stays_on_the_line(self):
        for rec, quote in (("Wait, then run `make`", "run make"), ("Wait, then **run** it", "run it"), ("See [the PR](http://x/1)", "See the PR")):
            rec_ = {}
            text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec=rec), rec_)
            text = text.replace(rec + "\n", rec + self.thread(quote) + "\n", 1)
            got = self.hand_over(text, self.block(self.NEW_SHA, rec=rec, when="02:00"), rec_)
            self.assertNotIn("orphan=1", got, rec)
            self.assertIn(rec + self.thread(quote), got)

    def test_a_thread_in_the_middle_of_our_line_does_not_make_the_line_the_persons(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec="Merge now, fine", ships=["a.py: x"]), rec)
        text = text.replace("Merge now,", "Merge now," + self.thread("Merge now,") + "", 1).replace("a.py", "a.py" + self.thread("a.py", "c2"), 1)
        text = text.replace(f"{self.OLD_SHA}, into main", f"{self.OLD_SHA}" + self.thread(self.OLD_SHA[:8], "c3") + ", into main", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Wait, later", ships=["b.py: y"], when="02:00"), rec)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)
        for gone in ("Merge now", "a.py: x", "fine", self.OLD_SHA, "01:00."):
            self.assertNotIn(gone, re.sub(r"<!--.*?-->", "", got, flags=re.S))
        self.assertEqual(got.count("sheaf-comment"), 3)
        self.assertEqual(anchor_problems(got), [])
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, rec="Wait, later", ships=["b.py: y"], when="02:00"), rec), got)

    def test_a_line_with_a_thread_in_the_middle_that_did_not_change_stands_as_it_was(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec="Merge now, fine"), rec)
        text = text.replace("Merge now,", "Merge now," + self.thread("Merge now,"), 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Merge now, fine", when="02:00"), rec)
        self.assertIn("Merge now," + self.thread("Merge now,") + " fine\n", got)
        self.assertNotIn("orphan=1", got)

    def test_a_quote_with_an_underscore_stays_on_its_line(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec="fix snake_case"), rec)
        text = text.replace("snake_case\n", "snake_case" + self.thread("snake_case") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="fix snake_case", when="02:00"), rec)
        self.assertNotIn("orphan=1", got)

    def test_a_line_of_ours_that_has_no_shape_is_replaced_when_the_record_lists_it(self):
        rec = {}
        mine = lambda sha, c: self.block(sha).replace("  - Pinned", f"  - Read by the scan: CI {c}\n  - Pinned")
        text = self.hand_over(self.page(""), mine(self.OLD_SHA, "green"), rec)
        got = self.hand_over(text, mine(self.NEW_SHA, "red"), rec)
        self.assertNotIn("CI green", got)
        self.assertEqual(got.count("Read by the scan"), 1)

    def test_words_the_person_typed_after_a_mid_line_thread_stay_and_the_old_pin_goes(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace(f"{self.OLD_SHA}, into main", f"{self.OLD_SHA}" + self.thread(self.OLD_SHA[:8], "c3") + ", into main (checked)", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)
        self.assertEqual(got.count("Pinned commit:"), 1)
        self.assertIn("(checked)", got)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, when="02:00"), rec), got)

    def test_an_unchanged_line_with_no_shape_keeps_its_thread_and_the_persons_next_line_stays_put(self):
        rec = {}
        mine = lambda sha: self.block(sha).replace("  - Pinned", "  - Read by the scan: opened x.\n  - Pinned")
        text = self.hand_over(self.page(""), mine(self.OLD_SHA), rec)
        text = text.replace("opened x.\n", "opened x." + self.thread("opened x.") + "\n  - my note\n", 1)
        got = self.hand_over(text, mine(self.NEW_SHA), rec)
        self.assertNotIn("orphan=1", got)
        self.assertLess(got.index("my note"), got.index("Pinned commit"))
        self.assertEqual(self.hand_over(got, mine(self.NEW_SHA), rec), got)

    def test_a_thread_in_the_middle_of_the_task_line_does_not_double_its_words(self):
        rec = {}
        block = "- [ ] Merge a/b#1: fix the bug\n  - Pinned commit: " + self.OLD_SHA + "\n"
        text = self.hand_over(self.page(""), block, rec)
        text = text.replace("fix the bug", "fix the" + self.thread("fix the") + " bug", 1)
        got = self.hand_over(text, block, rec)
        self.assertEqual(got, text)

    def test_a_thread_whose_words_are_still_the_end_of_the_new_line_stays_on_it(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("Merge it.\n", "Merge it." + self.thread("Merge it.") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertIn("Merge it." + self.thread("Merge it."), got)
        self.assertNotIn("orphan=1", got)
        self.assertEqual(anchor_problems(got), [])

    def test_a_thread_on_a_ships_bullet_that_is_gone_keeps_an_anchor(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, ships=["restart worker"]), rec)
        text = text.replace("restart worker\n", "restart worker" + self.thread("restart worker") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, ships=["restart the queue"]), rec)
        self.assertEqual(anchor_problems(got), [])
        self.assertIn("Wait for Friday.", got)
        self.assertEqual(got.count("sheaf-comment"), 1)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, ships=["restart the queue"]), rec), got)

    def test_a_thread_with_the_quote_in_entities_is_checked_decoded(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, rec="a & b"), rec)
        text = text.replace("a & b\n", "a & b" + self.thread("a &amp; b") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="a & b", when="02:00"), rec)
        self.assertNotIn("orphan=1", got)

    def test_two_threads_on_one_line_each_keep_their_own_anchor(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("Merge it.\n", "Merge it." + self.thread("Merge it.") + self.thread("it.", "c2") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, rec="Wait."), rec)
        self.assertEqual(anchor_problems(got), [])
        self.assertEqual(got.count("sheaf-comment"), 2)
        self.assertEqual(got.count("orphan=1"), 1)                           # "it." is not the end of "Wait."

    def test_a_ships_bullet_ending_in_a_quote_mark_next_to_repeated_bullets_keeps_its_own_thread(self):
        old = ("- [ ] Deploy a/b#1: x\n  - What ships:\n    - go\n    - go" + self.thread("go", "c1") + "\n    - go'" + self.thread("go'", "c2") + "\n"
               "  - Pinned commit: " + self.OLD_SHA + "\n")
        new = old.replace(self.thread("go", "c1"), "").replace(self.thread("go'", "c2"), "").replace(self.OLD_SHA, self.NEW_SHA)
        got = put_after(self.page(old), "a/b#1", new)
        self.assertEqual(got, self.page(old.replace(self.OLD_SHA, self.NEW_SHA)))

    def test_text_after_a_threads_closing_arrow_on_a_bullet_is_not_part_of_the_bullet(self):
        text = ("- [ ] Deploy a/b#1: x\n  - What ships:\n    - restart" + self.thread("restart") + " PERSON: only after Friday\n    - second\n")
        self.assertEqual(deskfile.parse(text)[0].ships, ["- restart", "- second"])


    # Without a valid record of the item, nothing on the page is taken for AgentView's: no pin is read from it, and a
    # hand-over adds its lines to the person's page and replaces and removes none.
    PERSON_PIN = "c" * 40

    def person_page(self):
        return self.page(f"- [ ] Merge a/b#1: what it does\n  - Recommendation: wait, mine\n  - Pinned commit: {self.PERSON_PIN}, mine\n")

    def test_a_line_shaped_like_a_pin_pins_nothing_without_a_record_for_the_item(self):
        text = self.person_page()
        other = {"a/b#2": {"lines": ["- [ ] Merge a/b#2: next"], "prev": []}}
        for record in (None, {}, other):
            self.assertEqual(deskfile.parse(text, record)[0].pinned, "", record)

    def test_a_pin_is_read_from_the_recorded_line_and_not_from_one_the_person_added_above_it(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Recommendation", f"  - Pinned commit: {self.PERSON_PIN}, mine\n  - Recommendation", 1)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(text, rec)}["a/b#1"], self.OLD_SHA)

    def test_a_hand_over_without_a_record_replaces_and_removes_none_of_the_persons_lines(self):
        for rec in ({}, {"a/b#2": {"lines": ["- [ ] Merge a/b#2: next"], "prev": []}}):
            got = deskfile.put(self.person_page(), "a/b#1", self.block(self.NEW_SHA), record=rec)
            for kept in ("- [ ] Merge a/b#1: what it does\n", "  - Recommendation: wait, mine\n", f"  - Pinned commit: {self.PERSON_PIN}, mine\n"):
                self.assertEqual(got.count(kept), 1, kept)
            self.assertIn(f"  - Pinned commit: {self.NEW_SHA}, into main\n", got)
            self.assertEqual([i.key for i in deskfile.parse(got, rec)], ["a/b#1", "a/b#2"])
            self.assertEqual(deskfile.parse(got, rec)[0].pinned, self.NEW_SHA)

    def test_a_corrupt_record_replaces_and_removes_nothing_and_the_next_hand_over_is_recorded(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
        self.addCleanup(lambda: os.environ.pop("XDG_RUNTIME_DIR") if old is None else os.environ.update(XDG_RUNTIME_DIR=old))
        f = tmp / "state" / "merge-desk.md"
        deskfile.put_item("a/b#1", self.block(self.OLD_SHA), file=f)
        (tmp / "state" / ".merge-desk.own.json").write_text("{not json")
        self.assertEqual(deskfile.items(f)[0].pinned, "")
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA), file=f)
        self.assertIn(f"Pinned commit: {self.OLD_SHA}", f.read_text())
        self.assertEqual(deskfile.items(f)[0].pinned, self.NEW_SHA)
        deskfile.put_item("a/b#1", self.block(self.OLD_SHA, when="03:00"), file=f)
        self.assertEqual(deskfile.items(f)[0].pinned, self.OLD_SHA)

    def legacy(self):
        """A page written before there was a record: (its file, the record's path)."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
        self.addCleanup(lambda: os.environ.pop("XDG_RUNTIME_DIR") if old is None else os.environ.update(XDG_RUNTIME_DIR=old))
        f = tmp / "state" / "merge-desk.md"
        deskfile.put_item("a/b#1", self.block(self.OLD_SHA, rec="R1"), file=f)
        deskfile.put_item("a/b#2", self.block(self.OLD_SHA, rec="R1").replace("a/b#1", "a/b#2"), file=f)
        rec = f.parent / ".merge-desk.own.json"
        rec.unlink()
        return f, rec

    def test_adopt_on_a_legacy_page_then_a_hand_over_replaces_the_old_lines(self):
        f, rec = self.legacy()
        self.assertEqual(deskfile.adopt(f), (["a/b#1", "a/b#2"], []))
        self.assertEqual({i.key: i.pinned for i in deskfile.items(f)}, {"a/b#1": self.OLD_SHA, "a/b#2": self.OLD_SHA})
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, rec="R2", when="02:00"), file=f)
        got = f.read_text()
        self.assertEqual(got.count(f"Pinned commit: {self.OLD_SHA}"), 1)           # a/b#2's only
        one = got[got.index("Deploy a/b#1"):got.index("Deploy a/b#2")]
        self.assertEqual((one.count("Recommendation"), one.count("Handed over"), one.count("Pinned commit")), (1, 1, 1))
        self.assertIn("Recommendation: R2", one)

    def test_adopt_leaves_an_item_that_has_a_record_alone(self):
        f, rec = self.legacy()
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, rec="R2"), file=f)      # a/b#1 has an entry again, a/b#2 has none
        before = json.loads(rec.read_text())["a/b#1"]
        self.assertEqual(deskfile.adopt(f), (["a/b#2"], []))
        self.assertEqual(json.loads(rec.read_text())["a/b#1"], before)

    def test_adopt_run_twice_gives_the_same_record_and_the_same_page(self):
        f, rec = self.legacy()
        deskfile.adopt(f)
        first, page = rec.read_text(), f.read_text()
        self.assertEqual(deskfile.adopt(f), ([], []))
        self.assertEqual((rec.read_text(), f.read_text()), (first, page))

    def test_adopt_does_not_take_an_indented_person_line_outside_the_ships_list(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "    - person indented note\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, rec="R2", when="02:00"), file=f)
        self.assertIn("    - person indented note\n", f.read_text())

    def test_adopt_skips_an_item_with_two_pin_lines_and_says_so(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace(f"  - Pinned commit: {self.OLD_SHA}", f"  - Pinned commit: {self.NEW_SHA}, my pin\n  - Pinned commit: {self.OLD_SHA}", 1))
        done, skipped = deskfile.adopt(f)
        self.assertEqual((done, skipped), (["a/b#2"], ["a/b#1"]))
        self.assertEqual({i.key: i.pinned for i in deskfile.items(f)}["a/b#1"], "")

    def test_adopt_refuses_a_record_that_cannot_be_read_and_leaves_it(self):
        f, rec = self.legacy()
        rec.write_text("{not json")
        with self.assertRaises(OSError):
            deskfile.adopt(f)
        self.assertEqual(rec.read_text(), "{not json")

    def test_adopt_keeps_the_ships_list_whole_across_a_thread_on_a_line_of_its_own(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "  - What ships:\n    - Outside GitHub: one\n  " + self.thread("x") + "\n    - Outside GitHub: two\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, ships=["x"], when="02:00"), file=f)
        got = f.read_text()
        self.assertNotIn("Outside GitHub: two\n", got)
        self.assertNotIn("Outside GitHub: one\n", got)

    def test_adopt_checks_the_record_under_the_lock(self):
        f, rec = self.legacy()
        real = deskfile.locked

        @contextlib.contextmanager
        def corrupting(file=None):
            with real(file) as got:
                rec.write_text("{not json")                      # changed after the check outside the lock would have run
                yield got
        with mock.patch.object(deskfile, "locked", corrupting):
            with self.assertRaises(OSError):
                deskfile.adopt(f)
        self.assertEqual(rec.read_text(), "{not json")

    def test_adopt_reports_a_case_duplicate_key_too(self):
        f, rec = self.legacy()
        f.write_text(f.read_text() + f.read_text().split("Deploy a/b#1", 1)[1].split("- [ ] Deploy a/b#2")[0].join(["- [ ] Deploy A/b#1", ""]))
        done, skipped = deskfile.adopt(f)
        self.assertEqual(sorted(k.lower() for k in done + skipped), ["a/b#1", "a/b#1", "a/b#2"])
        self.assertEqual(len(done), 2)

    def test_adopt_does_not_take_a_bullet_after_a_blank_line_in_the_ships_list(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "  - What ships:\n    - Outside GitHub: one\n\n    - the person's bullet\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, ships=["x"], when="02:00"), file=f)
        self.assertIn("    - the person's bullet\n", f.read_text())
        self.assertNotIn("Outside GitHub: one\n", f.read_text())

    def test_adopt_reads_an_empty_record_with_a_space_in_it(self):
        f, rec = self.legacy()
        rec.write_text("{ }")
        self.assertEqual(deskfile.adopt(f), (["a/b#1", "a/b#2"], []))

    def test_adopt_takes_a_ticked_task_line_so_a_hand_over_updates_the_title(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("- [ ] Deploy a/b#1", "- [x] Deploy a/b#1", 1))
        deskfile.adopt(f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, rec="R2").replace("what it does", "new title"), file=f)
        self.assertIn("- [ ] Deploy a/b#1: new title\n", f.read_text())

    def test_adopt_does_not_take_a_line_of_no_known_shape(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "  - my own note\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        self.assertNotIn("my own note", "".join(json.loads(rec.read_text())["a/b#1"]["lines"]))

    def test_a_task_line_the_person_changed_stays_theirs_and_the_item_keeps_one_task_line(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("what it does\n", "what it does, and I added this" + self.thread("what it does", "c9") + "\n", 1)
        got = self.hand_over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual(got.count("Deploy a/b#1"), 1)
        self.assertIn("what it does, and I added this" + self.thread("what it does", "c9") + "\n", got)
        self.assertEqual(sorted(i.key for i in deskfile.parse(got, rec)), ["a/b#1", "a/b#2"])
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)
        self.assertEqual(self.hand_over(got, self.block(self.NEW_SHA, when="02:00"), rec), got)

    def test_a_task_line_that_is_as_recorded_is_replaced(self):
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA), rec)
        got = self.hand_over(text, self.block(self.NEW_SHA).replace("what it does", "what it now does"), rec)
        self.assertIn("- [ ] Deploy a/b#1: what it now does\n", got)
        self.assertEqual(got.count("Deploy a/b#1"), 1)

    THIRD_SHA, FOURTH_SHA = "c" * 40, "d" * 40

    def test_adopt_does_not_take_a_note_of_the_persons_under_what_ships(self):
        """Ticket 31a: a four-space line under `What ships:` is ours only in a shape AgentView writes."""
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "  - What ships:\n    - Fires on push to main: ci.yml\n      - ci.yml:3: run: deploy\n    - NOTE: deploy manually\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        self.assertNotIn("NOTE: deploy manually", rec.read_text())
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, ships=["Outside GitHub: x"], when="02:00"), file=f)
        got = f.read_text()
        self.assertIn("    - NOTE: deploy manually\n", got)
        self.assertNotIn("Fires on push to main: ci.yml", got)               # what AgentView wrote is still replaced
        self.assertNotIn("ci.yml:3: run: deploy", got)

    def test_adopt_does_not_take_a_persons_line_nested_under_one_of_ours(self):
        f, rec = self.legacy()
        f.write_text(f.read_text().replace("  - Pinned commit:", "  - What ships:\n    - Commits that go out (1):\n      - abcdef0 fix it\n      - my note\n  - Pinned commit:", 1))
        deskfile.adopt(f)
        deskfile.put_item("a/b#1", self.block(self.NEW_SHA, ships=["Outside GitHub: x"], when="02:00"), file=f)
        got = f.read_text()
        self.assertIn("      - my note\n", got)
        self.assertNotIn("abcdef0 fix it", got)

    def ships(self):
        return ["Outside GitHub: x", "Fires on push to main: ci.yml"]

    def test_a_page_is_not_behind_because_the_person_put_a_copy_of_an_old_pin_line_in_place_of_ours(self):
        """Ticket 31b: the page holds the last generation (B); the person removed its pin and handed-over lines and typed
        a copy of the pin line of the generation before (A). More of A's lines match than of B's, but the page is not A."""
        rec = {}
        text = self.hand_over(self.page(""), self.block(self.OLD_SHA, ships=self.ships()), rec)
        text = self.hand_over(text, self.block(self.NEW_SHA, ships=self.ships(), when="02:00"), rec)
        copy_ = f"  - Pinned commit: {self.OLD_SHA}, into main\n"
        text = text.replace(f"  - Pinned commit: {self.NEW_SHA}, into main\n", copy_).replace("  - Handed over by a session, 2026-11-14 02:00.\n", "")
        got = self.hand_over(text, self.block(self.THIRD_SHA, ships=self.ships(), when="03:00"), rec)
        self.assertEqual(got.count(copy_), 1)
        self.assertEqual(got.count(f"Pinned commit: {self.THIRD_SHA}"), 1)

    def test_prev_after_failed_writes_is_one_generation_and_a_copy_of_an_old_line_is_kept_once_the_page_is_new(self):
        rec = {}
        first = self.hand_over(self.page(""), self.block(self.OLD_SHA, ships=self.ships()), rec)       # A, on the page
        self.hand_over(first, self.block(self.NEW_SHA, ships=self.ships(), when="02:00"), rec)        # A to B: not written
        self.hand_over(first, self.block(self.THIRD_SHA, ships=self.ships(), when="03:00"), rec)      # B to C: not written
        text = self.hand_over(first, self.block(self.FOURTH_SHA, ships=self.ships(), when="04:00"), rec)
        self.assertEqual(rec["a/b#1"]["prev"], deskfile._heads(self.block(self.OLD_SHA, ships=self.ships())))     # one generation, the one the page held
        for sha in (self.OLD_SHA, self.NEW_SHA, self.THIRD_SHA):
            copy_ = f"  - Pinned commit: {sha}, into main\n"
            mine = text.replace("  - What ships:\n", copy_ + "  - What ships:\n", 1)
            got = self.hand_over(mine, self.block(self.FOURTH_SHA, ships=self.ships(), when="05:00"), copy.deepcopy(rec))
            self.assertEqual(got.count(copy_), 1, sha)


class Comments(unittest.TestCase):
    """Sheaf keeps the person's comments inside the file; their text is never structure."""

    def test_a_list_line_in_a_comment_does_not_end_the_item(self):
        text = ("## Pull requests waiting for your merge\n"
                "- [ ] Merge a/b#1: first\n  - Pinned commit: " + "a" * 40 + "\n"
                "<!-- comment:\n- do not merge until Friday\n## Pull requests waiting for your merge\n-->\n"
                "- [ ] Merge a/b#2: second\n")
        self.assertEqual(deskfile.drop(text, "a/b#1"), "## Pull requests waiting for your merge\n- [ ] Merge a/b#2: second\n")
        replaced = deskfile.put(text, "a/b#1", "- [ ] Merge a/b#1: new\n")
        self.assertIn("<!-- comment:\n- do not merge until Friday\n## Pull requests waiting for your merge\n-->\n", replaced)   # the person's, so kept
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
        self.assertEqual(parse_after(text)[0].pinned, "b" * 40)

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


class ThreadsOnOneLine(unittest.TestCase):
    """Ticket 23: what sheaf and the person put on one of AgentView's lines survives hand-overs in its place, a comment
    that is not a sheaf thread is never touched, and a comment the person left open does not swallow the page."""

    OLD_SHA, NEW_SHA, THIRD_SHA = "a" * 40, "b" * 40, "c" * 40

    def thread(self, quote, cid, kind="sheaf-comment"):
        return f'<!-- {kind} id={cid} by="Thierry" at=2026-11-14T01:00 status=open quote="{quote}"\nWait for {cid}.\n-->'

    def block(self, sha, when="01:00", ships=()):
        out = "- [ ] Deploy a/b#1: what it does\n  - Recommendation: Merge it.\n"
        if ships:
            out += "  - What ships:\n" + "".join(f"    - {b}\n" for b in ships)
        return out + f"  - Pinned commit: {sha}, into main\n  - Handed over by a session, 2026-11-14 {when}.\n"

    def page(self, body):
        return ("# D\n\n## Pull requests waiting for your merge\n" + body + "- [ ] Merge a/b#2: next\n"
                "  - Pinned commit: " + "d" * 40 + "\n")

    def over(self, text, block, rec):
        return deskfile.put(text, "a/b#1", block, record=rec)

    def test_two_threads_and_the_persons_words_on_one_line_keep_their_order_across_two_hand_overs(self):
        rec, c1, c2 = {}, self.thread("Merge", "c1"), self.thread("it.", "c2")
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        line = f"  - Recommendation: Merge{c1} it.{c2} and fine\n"
        text = text.replace("  - Recommendation: Merge it.\n", line, 1)
        first = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        second = self.over(first, self.block(self.THIRD_SHA, when="03:00"), rec)
        for got in (first, second):
            self.assertIn(f"  - Recommendation: Merge{c1} it.{c2}\n", got)      # each thread still follows the words it quotes
            self.assertEqual(got.count("and fine"), 1)                           # the person's words, once, on a line of their own
            self.assertNotIn("orphan=1", got)
        self.assertEqual(deskfile.put(second, "a/b#1", self.block(self.THIRD_SHA, when="03:00"), record=rec), second)

    def test_a_comment_that_is_not_a_sheaf_thread_is_never_marked_orphan(self):
        rec, note = {}, '<!-- todo quote="restart" check with Sven -->'
        text = self.over(self.page(""), self.block(self.OLD_SHA, ships=["restart"]), rec)
        text = text.replace("    - restart\n", f"    - restart{note}\n", 1)
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)           # the new block has no ships list: the line is gone
        self.assertIn(note, got)
        self.assertNotIn("orphan=1", got)
        sheaf = self.thread("restart", "c1")
        text = self.over(self.page(""), self.block(self.OLD_SHA, ships=["restart"]), rec)
        text = text.replace("    - restart\n", f"    - restart{sheaf}\n", 1)
        self.assertIn("orphan=1", self.over(text, self.block(self.NEW_SHA, when="02:00"), rec))   # a sheaf thread still is

    def test_an_unclosed_comment_in_a_persons_line_leaves_the_following_items_intact(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec) + "- [ ] Merge a/b#4: after\n"
        text = text.replace("  - Recommendation: Merge it.\n", "  - Recommendation: Merge it.\n  my note <!-- never closed\n", 1)
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)     # the new lines are not in the comment
        self.assertIn("my note <!-- never closed", got)
        self.assertIn("- [ ] Merge a/b#4: after", got)                          # what the comment swallowed is kept as it was, once
        self.assertEqual(got.count("Merge a/b#4"), 1)
        self.assertEqual(got.count("<!--"), got.count("-->"))                  # and the comment ends: it swallows nothing of what comes next
        self.assertEqual(self.over(got, self.block(self.NEW_SHA, when="02:00"), rec), got)        # a second, identical hand-over changes nothing

    def test_settle_replaces_a_result_line_that_carries_a_thread_and_keeps_the_thread(self):
        rec, c1 = {}, self.thread("Not merged: CI is red", "c1")
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        text = text.replace("Not merged: CI is red\n", f"Not merged: CI is red{c1}\n", 1)
        got = deskfile.settle(text, "a/b#1", "Merged as abcdef0 at 10:00", record=rec)
        self.assertNotIn("  - Not merged: CI is red", got)          # the old result line is replaced...
        self.assertIn("Wait for c1.", got)                          # ...and the thread on it is kept, as an orphan, on a line of its own
        self.assertIn("orphan=1", got)
        self.assertEqual(got.count("  - Merged as abcdef0 at 10:00"), 1)


class CopyOfOurLine(unittest.TestCase):
    """A person's byte-identical copy of a line AgentView wrote is theirs (ticket 26): the record says in what order
    AgentView wrote its lines and how many identical lines stood before each, so a copy out of its place is not ours."""

    OLD_SHA, NEW_SHA = "a" * 40, "b" * 40
    PIN = "  - Pinned commit: {}, into main\n"

    def block(self, sha, rec="Merge it.", when="01:00"):
        return (f"- [ ] Deploy a/b#1: what it does\n  - Recommendation: {rec}\n" + self.PIN.format(sha)
                + f"  - Handed over by a session, 2026-11-14 {when}.\n")

    def page(self, body):
        return "# D\n\n## Pull requests waiting for your merge\n" + body + "- [ ] Merge a/b#2: next\n"

    def over(self, text, block, rec):
        return deskfile.put(text, "a/b#1", block, record=rec)

    def test_a_copy_of_the_pin_line_above_the_recommendation_is_kept_and_ours_is_replaced(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Recommendation:", self.PIN.format(self.OLD_SHA) + "  - Recommendation:", 1)      # the person's copy, first
        got = self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        old, new, recommendation = (got.index(self.PIN.format(self.OLD_SHA)), got.index(self.PIN.format(self.NEW_SHA)),
                                    got.index("Recommendation: R2"))
        self.assertEqual(got.count(self.PIN.format(self.OLD_SHA)), 1)           # theirs stays, in its place
        self.assertLess(old, recommendation)
        self.assertLess(recommendation, new)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)

    THIRD_SHA = "c" * 40

    def test_a_copy_of_an_old_pin_line_survives_a_third_hand_over(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Recommendation:", self.PIN.format(self.OLD_SHA) + "  - Recommendation:", 1)      # the person's copy of pin A
        text = self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        text = self.over(text, self.block(self.THIRD_SHA, rec="R3", when="03:00"), rec)
        self.assertEqual(text.count(self.PIN.format(self.OLD_SHA)), 1)            # theirs stays through the third
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(text, rec)}["a/b#1"], self.THIRD_SHA)

    def test_a_page_the_record_has_not_caught_up_with_is_still_replaced_whole(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)             # the record moved on, the write did not finish
        got = self.over(text, self.block(self.THIRD_SHA, when="03:00"), rec)
        self.assertEqual(got.count("Pinned commit"), 1)
        self.assertEqual(got.count("Handed over"), 1)

    def test_a_copy_of_the_recommendation_line_after_ours_is_kept_and_ours_is_replaced(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Pinned commit", "  - Recommendation: Merge it.\n  - Pinned commit", 1)           # the person's copy, after ours
        got = self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        self.assertEqual(got.count("Recommendation: Merge it."), 1)
        self.assertEqual(got.count("Recommendation: R2"), 1)

    def test_the_pin_is_read_from_the_recorded_place_not_the_first_line_of_that_text(self):
        record = {"a/b#1": {"lines": ["- [ ] Deploy a/b#1: what it does", "  - Recommendation: Merge it.",
                                      self.PIN.format(self.NEW_SHA).rstrip("\n"), "  - Handed over by a session, 2026-11-14 01:00."],
                            "prev": [], "at": [0, 0, 0, 0]}}
        block = self.block(self.NEW_SHA).replace("  - Recommendation", self.PIN.format(self.NEW_SHA) + "  - Recommendation", 1)
        logical = deskfile._logical(block)
        kinds = deskfile._kinds(logical, Counter(record["a/b#1"]["lines"]), orders=deskfile._orders(record["a/b#1"]))
        self.assertEqual([i for i, k in enumerate(kinds) if k == ("pin",)], [3])        # the line after the recommendation

    def test_a_record_written_before_ordinals_is_still_read_and_is_rewritten_with_them(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        del rec["a/b#1"]["at"]
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(text, rec)}["a/b#1"], self.OLD_SHA)
        got = self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        self.assertEqual(got.count("Pinned commit"), 1)
        self.assertEqual({i.key: i.pinned for i in deskfile.parse(got, rec)}["a/b#1"], self.NEW_SHA)
        self.assertEqual(rec["a/b#1"]["at"], [0, 0, 0, 0])

    def test_the_record_keeps_the_place_of_ours_among_identical_lines_the_person_left(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("  - Handed over", self.PIN.format(self.OLD_SHA) + "  - Handed over", 1)        # a copy after ours
        self.over(text, self.block(self.OLD_SHA, when="02:00"), rec)
        self.assertEqual(rec["a/b#1"]["at"][2], 0)                                                     # ours is the first, the copy stays after

    def test_adopt_writes_the_places(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "merge-desk.md"
        f.write_text(self.page(self.block(self.OLD_SHA)))
        self.assertEqual(deskfile.adopt(f), (["a/b#1", "a/b#2"], []))
        self.assertEqual(json.loads((d / ".merge-desk.own.json").read_text())["a/b#1"]["at"], [0, 0, 0, 0])


class Leftovers(unittest.TestCase):
    """Ticket 28: a comment the person left open, line ends of a CRLF page, and the loose ends of tickets 23 and 27."""

    OLD_SHA, NEW_SHA, THIRD_SHA = "a" * 40, "b" * 40, "c" * 40
    PIN = "  - Pinned commit: {}, into main\n"
    THREAD = '<!-- sheaf-comment id=c9 by="Thierry" at=2026-11-14T01:00 status=open quote="QUOTE" -->'

    def block(self, sha, rec="Merge it.", when="01:00"):
        return (f"- [ ] Deploy a/b#1: what it does\n  - Recommendation: {rec}\n" + self.PIN.format(sha)
                + f"  - Handed over by a session, 2026-11-14 {when}.\n")

    def page(self, body):
        return "# D\n\n## Pull requests waiting for your merge\n" + body + "- [ ] Merge a/b#2: next\n  - Pinned commit: " + "d" * 40 + ", into main\n"

    def over(self, text, block, rec, key="a/b#1"):
        return deskfile.put(text, key, block, record=rec)

    def keys(self, text, rec):
        return [i.key for i in deskfile.parse(text, rec)]

    def live(self, text):
        """The page without its comments: what is on it for a reader."""
        return re.sub(r"<!--.*?-->", "", text, flags=re.S)

    def closed(self, text):
        return deskfile._open_at(text) is None

    def test_a_comment_left_open_on_one_of_our_lines_hides_no_item_after_a_hand_over(self):
        text = self.page(self.block(self.OLD_SHA))
        rec = written(text)
        text = text.replace("Merge it.\n", "Merge it.<!-- oops\n", 1)
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2"])
        self.assertTrue(self.closed(got))
        again = self.over(got, self.block(self.THIRD_SHA, when="03:00"), rec)
        live = self.live(again)
        self.assertEqual((live.count("Pinned commit: " + self.THIRD_SHA), live.count("Pinned commit: " + self.NEW_SHA), live.count("Recommendation"), live.count("a/b#2")), (1, 0, 1, 1))
        self.assertEqual(self.keys(again, rec), ["a/b#1", "a/b#2"])

    def test_an_item_hidden_by_a_comment_left_open_above_it_is_handed_over_once(self):
        text = self.page(self.block(self.OLD_SHA))
        rec = written(text)
        text = text.replace("Merge it.\n", "Merge it.<!-- oops\n", 1)
        got = deskfile.put(text, "a/b#2", "- [ ] Merge a/b#2: next\n  - Pinned commit: " + "e" * 40 + ", into main\n", record=rec)
        self.assertEqual(got.count("Merge a/b#2"), 1)
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2"])
        self.assertIn("e" * 40, got)

    def test_a_comment_left_open_on_the_task_line_is_closed_and_the_block_is_not_added_twice(self):
        text = self.page(self.block(self.OLD_SHA))
        rec = written(text)
        text = text.replace("what it does\n", "what it does <!-- oops\n", 1)
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2"])
        self.assertTrue(self.closed(got))
        live = self.live(got)
        self.assertEqual((live.count("Recommendation"), live.count("Pinned commit: " + self.NEW_SHA), live.count("Handed over")), (1, 1, 1))
        again = self.live(self.over(got, self.block(self.THIRD_SHA, when="03:00"), rec))
        self.assertEqual((again.count("Recommendation"), again.count("Pinned commit: " + self.THIRD_SHA), again.count("Handed over")), (1, 1, 1))
        self.assertEqual(again.count("what it does"), 1)

    def test_a_comment_left_open_on_the_result_line_does_not_send_the_next_result_to_the_next_item(self):
        text = self.page(self.block(self.OLD_SHA))
        rec = written(text)
        text = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        text = text.replace("Not merged: CI is red\n", "Not merged: CI is red<!-- oops\n", 1)
        got = deskfile.settle(text, "a/b#1", "Not merged: CI is still red", record=rec)
        items = {i.key: i.block for i in deskfile.parse(got, rec)}
        self.assertEqual(sorted(items), ["a/b#1", "a/b#2"])
        self.assertIn("CI is still red", items["a/b#1"])
        self.assertNotIn("Not merged", items["a/b#2"])
        self.assertTrue(self.closed(got))

    def test_a_copy_of_an_old_pin_line_stays_when_the_person_also_edited_the_current_pin_line(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = self.over(text, self.block(self.NEW_SHA), rec)
        text = text.replace(self.PIN.format(self.NEW_SHA), self.PIN.format(self.OLD_SHA) + f"  - Pinned commit: {self.NEW_SHA}, into main (checked)\n", 1)
        got = self.over(text, self.block(self.THIRD_SHA), rec)
        self.assertEqual(got.count(self.PIN.format(self.OLD_SHA)), 1)
        self.assertIn(f"{self.NEW_SHA}, into main (checked)", got)

    def test_prev_stays_one_generation_long_while_writes_keep_failing(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        for n in range(8):                                               # the record moves on, the write does not reach the page
            self.over(text, self.block(str(n) * 40, when=f"0{n}:00"), rec)
        self.assertLessEqual(len(rec["a/b#1"]["prev"]), len(deskfile._heads(self.block(self.OLD_SHA))))
        got = self.over(text, self.block(self.THIRD_SHA, when="09:00"), rec)
        self.assertEqual((got.count("Pinned commit: " + self.THIRD_SHA), got.count("Handed over"), got.count("Recommendation")), (1, 1, 1))
        self.assertNotIn(self.OLD_SHA, got)

    def lone_ends(self, text):
        return re.findall(r"(?<!\r)\n|\r(?!\n)", text)

    def test_a_crlf_page_keeps_one_kind_of_line_end_after_a_hand_over_and_a_settle(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec).replace("\n", "\r\n")
        got = self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)
        self.assertEqual(self.lone_ends(got), [])
        got = deskfile.settle(got, "a/b#1", "Not merged: CI is red", record=rec)
        self.assertEqual(self.lone_ends(got), [])
        got = deskfile.put(got, "a/b#3", "- [ ] Merge a/b#3: new\n", record=rec)
        self.assertEqual(self.lone_ends(got), [])

    def test_the_closing_added_on_a_crlf_page_leaves_no_lone_carriage_return(self):
        text = self.page(self.block(self.OLD_SHA)).replace("\n", "\r\n")
        rec = written(text)
        text = text.replace("Merge it.\r\n", "Merge it.<!-- oops\r\n", 1)
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual(self.lone_ends(got), [])
        self.assertNotIn("\r -->", got)
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2"])

    def test_carry_alone_closes_an_open_comment_without_a_lone_carriage_return(self):
        old = "- [ ] Deploy a/b#1: x\r\n  - Recommendation: Merge it.<!-- oops\r\n"
        got = deskfile.carry(old, "- [ ] Deploy a/b#1: x\n", {"- [ ] Deploy a/b#1: x": 1, "  - Recommendation: Merge it.": 1})
        self.assertNotIn("\r -->", got)

    def test_a_task_line_without_a_colon_on_a_crlf_page_is_still_an_item(self):
        text = "# D\r\n\r\n## Pull requests waiting for your merge\r\n- [ ] Merge a/b#1\r\n  - Pinned commit: " + "a" * 40 + "\r\n- [ ] Install foo\r\n"
        self.assertEqual([i.key for i in deskfile.parse(text, {})], ["a/b#1", "install:foo"])

    def test_adopt_returns_each_key_once_when_edit_retries(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "merge-desk.md"
        f.write_text(self.page(self.block(self.OLD_SHA)))
        real = deskfile.edit

        def retrying(change, file=None):
            def both(t):
                first = copy.deepcopy(deskfile._held.record)
                change(t)
                deskfile._held.record = first                       # a retry starts from the stored record again
                return change(t)
            return real(both, file)
        with mock.patch.object(deskfile, "edit", retrying):
            self.assertEqual(deskfile.adopt(f), (["a/b#1", "a/b#2"], []))

    def settled(self, rec):
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        return deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)

    def test_settle_replaces_a_result_line_with_a_thread_in_its_middle(self):
        rec = {}
        text = self.settled(rec).replace("Not merged: CI is red", "Not merged: CI" + self.THREAD.replace("QUOTE", "CI") + " is red", 1)
        got = deskfile.settle(text, "a/b#1", "Not merged: CI is red again", record=rec)
        self.assertEqual(got.count("Not merged:"), 1)
        self.assertIn("Not merged: CI is red again", got)
        self.assertEqual(got.count("id=c9"), 1)

    def test_a_second_settle_with_the_same_result_keeps_it_above_the_thread_left_by_the_first(self):
        rec = {}
        text = self.settled(rec).replace("Not merged: CI is red", "Not merged: CI is red" + self.THREAD.replace("QUOTE", "CI is red"), 1)
        once = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        twice = deskfile.settle(once, "a/b#1", "Not merged: CI is red", record=rec)
        self.assertEqual(twice, once)
        self.assertLess(twice.index("Not merged: CI is red\n"), twice.index("orphan=1"))

    def three(self):
        """A page of three items; the thread on the third closes with the `-->` a comment left open on the first would need."""
        text = ("# D\n\n## Pull requests waiting for your merge\n" + self.block(self.OLD_SHA)
                + "- [ ] Merge a/b#2: next\n  - Pinned commit: " + "d" * 40 + ", into main\n"
                + "- [ ] Merge a/b#3: last\n  - Recommendation: wait." + self.THREAD.replace("QUOTE", "wait.") + "\n")
        return text, written(text)

    def test_a_comment_left_open_and_closed_by_a_later_threads_arrow_hides_no_item(self):
        text, rec = self.three()
        text = text.replace("Merge it.\n", "Merge it.<!-- oops\n", 1)
        self.assertEqual(self.keys(text, rec), ["a/b#1"])
        got = deskfile.put(text, "a/b#2", "- [ ] Merge a/b#2: next\n  - Pinned commit: " + "e" * 40 + ", into main\n", record=rec)
        self.assertEqual((got.count("Merge a/b#2"), got.count("id=c9")), (1, 1))
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2", "a/b#3"])
        got = self.over(text, self.block(self.NEW_SHA, when="02:00"), rec)
        self.assertEqual(self.keys(got, rec), ["a/b#1", "a/b#2", "a/b#3"])
        live = self.live(got)
        self.assertEqual((live.count("Pinned commit: " + self.NEW_SHA), live.count("Pinned commit: " + self.OLD_SHA), live.count("Handed over")), (1, 0, 1))

    def test_a_new_item_put_on_a_page_with_a_comment_left_open_is_visible(self):
        text = "# D\n\n## Pull requests waiting for your merge\n- [ ] Merge a/b#1: first\n  - Recommendation: x.<!-- oops\n"
        got = deskfile.put(text, "a/b#9", "- [ ] Merge a/b#9: new\n", record={})
        self.assertIn("a/b#9", self.keys(got, {}))
        self.assertTrue(self.closed(got))

    def test_the_stale_pin_is_still_replaced_when_the_person_edited_the_recommendation(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        self.over(text, self.block(self.NEW_SHA, rec="R2", when="02:00"), rec)             # the record moved on, the write did not finish
        text = text.replace("Recommendation: Merge it.", "Recommendation: Merge it, says the person.", 1)
        got = self.over(text, self.block(self.THIRD_SHA, rec="R3", when="03:00"), rec)
        self.assertEqual((got.count(self.OLD_SHA), got.count(self.NEW_SHA), got.count(self.THIRD_SHA), got.count("Handed over")), (0, 0, 1, 1))

    def test_settle_on_a_crlf_page_puts_the_result_above_the_blank_line_after_the_item(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec).replace("\n", "\r\n")
        text = text.replace("- [ ] Merge a/b#2", "\r\n- [ ] Merge a/b#2", 1)
        one = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        self.assertEqual(self.lone_ends(one), [])
        self.assertEqual(one, deskfile.settle(text.replace("\r\n", "\n"), "a/b#1", "Not merged: CI is red", record=rec).replace("\n", "\r\n"))

    def test_a_missing_section_on_a_crlf_page_is_made_with_crlf(self):
        text = "# D\r\n\r\nSome words.\r\n"
        got = deskfile.put(text, "install:foo", "- [ ] Install foo: x\r\n", section="install", record={})
        self.assertEqual(self.lone_ends(got), [])
        self.assertIn("## Local installs waiting for you\r\n- [ ] Install foo", got)

    def test_a_comment_that_holds_a_comment_closed_before_any_item_is_left_alone_and_nothing_loops(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec).replace("Merge it.\n", "Merge it.\n  <!-- old <!-- thread --> text -->\n", 1)
        got = deskfile.put(text, "a/b#3", "- [ ] Merge a/b#3: new\n", record=rec)
        self.assertEqual(got.count("-->"), text.count("-->"))
        self.assertIn("a/b#3", self.keys(got, rec))

    def test_a_persons_note_that_holds_a_list_line_and_a_comment_opener_is_left_alone(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec)
        text = text.replace("Merge it.\n", "Merge it.\n  <!-- note: write <!-- to open\n- [ ] Merge a/b#9: x\n  -->\n", 1)
        got = deskfile.put(text, "a/b#2", "- [ ] Merge a/b#2: next\n", record=rec)
        self.assertIn("<!-- note: write <!-- to open\n- [ ] Merge a/b#9: x\n  -->\n", got)
        self.assertNotIn("a/b#9", self.keys(got, rec))

    NOTE = '<!-- private note\n- [ ] Merge a/b#9: old\nperson tail\nliteral <!-- sheaf-comment x -->\nmore tail\n-->\n- [ ] Merge a/b#1: real\n'

    def test_drop_leaves_a_closed_note_that_holds_a_list_line_and_a_literal_thread_opener_whole(self):
        """Ticket 31c: the note closes itself, after the literal opener's own arrow; it is not a comment left open."""
        self.assertEqual(deskfile.drop(self.NOTE, "a/b#9", record={}), self.NOTE)
        self.assertTrue(self.closed(self.NOTE))

    def test_put_leaves_a_closed_note_that_holds_a_list_line_and_a_literal_thread_opener_closed(self):
        got = put_after(self.NOTE, "a/b#1", "- [ ] Merge a/b#1: real now\n")
        self.assertEqual(got, self.NOTE.replace("real\n", "real now\n"))
        got = deskfile.put(self.NOTE, "a/b#2", "- [ ] Merge a/b#2: new\n", record={})
        self.assertTrue(got.startswith(self.NOTE[:self.NOTE.index("-->") + 4]))
        self.assertEqual(self.keys(got, {}), ["a/b#1", "a/b#2"])

    def test_a_note_closed_after_the_literal_thread_is_told_apart_from_a_comment_a_thread_closes(self):
        left = "<!-- oops\n- [ ] Merge a/b#9: old\nand\n  <!-- sheaf-comment id=c9 by=\"T\" status=open quote=\"x\" -->\n- [ ] Merge a/b#1: real\n"
        self.assertEqual(deskfile._open_at(left), 0)
        self.assertIsNone(deskfile._open_at(self.NOTE))

    def test_settle_on_a_crlf_page_whose_last_line_has_no_line_end_keeps_one_kind(self):
        rec = {}
        text = self.over(self.page(""), self.block(self.OLD_SHA), rec).replace("\n", "\r\n")
        text = text[:text.index("- [ ] Merge a/b#2")] + text[text.index("- [ ] Merge a/b#2"):].rstrip("\r\n")
        text = text[:text.index("- [ ] Merge a/b#2")]                      # the item under test is the last one now, with no line end
        text = text.rstrip("\r\n")
        got = deskfile.settle(text, "a/b#1", "Not merged: CI is red", record=rec)
        self.assertEqual(self.lone_ends(got), [])

    def test_a_one_line_last_block_on_a_crlf_page_with_no_final_line_end_gets_crlf_from_put_and_settle(self):
        text = "# D\r\n\r\n## Local installs waiting for you\r\n- [ ] Install foo: x"
        rec = {}
        got = deskfile.put(text, "install:foo", "- [ ] Install foo: y\n", section="install", record=rec)
        self.assertEqual(self.lone_ends(got), [])
        got = deskfile.settle(text, "install:foo", "Installed as abcdef0 at 10:00", record=rec)
        self.assertEqual(self.lone_ends(got), [])
        got = deskfile.put(text, "install:bar", "- [ ] Install bar: z\n", section="install", record=rec)
        self.assertEqual(self.lone_ends(got), [])


if __name__ == "__main__":
    unittest.main()
