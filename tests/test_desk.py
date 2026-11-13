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

FAKE_GH = """#!/bin/sh
# fake gh: `gh pr view N -R repo --json ...` answers from $FAKE_GH_DIR/<repo with / as _>#<N>.json
[ "$1 $2" = "pr view" ] || { echo "fake gh: unexpected $*" >&2; exit 9; }
n=$3; repo=$5
f="$FAKE_GH_DIR/$(echo "$repo" | tr / _)#$n.json"
[ -f "$f" ] || { echo "GraphQL: Could not resolve to a PullRequest" >&2; exit 1; }
cat "$f"
"""


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
                 "PATH": f"{self.gh.parent}:{os.environ['PATH']}", "FAKE_GH_DIR": str(self.prs)})

    def ready(self, n=272, repo="sweatshop-ai/sheaf", what="the dictation time limit", rec="merge", *more):
        return self.run_desk("ready", repo, n, "--what", what, "--rec", rec, "--why", "CI green", *more)

    def text(self):
        return self.page.read_text()


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
