"""The merge desk's watcher: a ticked Merge item merges at the pinned commit, one at a time.

`deskwatch.tick()` runs in this process with `XDG_STATE_HOME` and `XDG_RUNTIME_DIR` under a throwaway
directory and `deskwatch.GH` set to a fake `gh` (a script that answers `pr view` and `pr merge` from a
folder of files and notes every call). Never the real GitHub, never the real state folder, never a real merge.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desk
import deskfile
import deskwatch

SHA = "ead9a1f" + "0" * 33
SHA2 = "b" * 40
MERGED_AS = "41678e3" + "1" * 33
REPO = "sweatshop-ai/sheaf"

FAKE_GH = f"""#!{sys.executable}
import json, os, sys, time
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
with open(d + "/calls.log", "a") as f:
    f.write(json.dumps({{"args": args, "path": os.environ.get("PATH"),
                         "log": open(os.environ["XDG_STATE_HOME"] + "/agentview/merge-desk.log").read().splitlines()[-1:]
                         if os.path.exists(os.environ["XDG_STATE_HOME"] + "/agentview/merge-desk.log") else []}}) + "\\n")
if args[:2] not in (["pr", "view"], ["pr", "merge"]):
    sys.exit(9)
n, repo = args[2], args[4]
f = d + "/" + repo.replace("/", "_") + "#" + n + ".json"
if not os.path.exists(f):
    print("Could not resolve to a PullRequest", file=sys.stderr)
    sys.exit(1)
pr = json.load(open(f))
if args[1] == "view":
    unknown = d + "/unknown-" + n
    if os.path.exists(unknown):
        left = int(open(unknown).read())
        if left > 0:
            open(unknown, "w").write(str(left - 1))
            pr["mergeable"] = "UNKNOWN"
    print(json.dumps(pr))
    sys.exit(0)
if os.path.exists(d + "/merge-fails"):
    print("GraphQL: Pull request is not mergeable", file=sys.stderr)
    sys.exit(1)
sha = args[args.index("--match-head-commit") + 1]
if sha != pr["headRefOid"]:
    print("head commit changed", file=sys.stderr)
    sys.exit(1)
with open(d + "/merges.log", "a") as m:
    m.write("start " + n + "\\n")
time.sleep(0.15)
pr["state"] = "MERGED"
pr["mergeCommit"] = {{"oid": "{MERGED_AS}"}}
json.dump(pr, open(f, "w"))
with open(d + "/merges.log", "a") as m:
    m.write("end " + n + "\\n")
"""


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
        self.prs = self.tmp / "prs"
        self.prs.mkdir()
        self.gh = self.tmp / "bin" / "gh"
        self.gh.parent.mkdir()
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IXUSR)
        env = {"XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_GH_DIR": str(self.prs)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(lambda: [os.environ.pop(k) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        self.page = deskfile.path()
        self.saved = (deskwatch.GH, deskwatch.sleep, deskwatch.log.error, deskwatch.GRACE)
        deskwatch.GRACE = 0
        deskwatch._warned.clear()
        self.sleeps = []
        deskwatch.GH = str(self.gh)
        deskwatch.sleep = self.sleeps.append
        deskwatch.log.error = lambda *a, **k: self.errors.append((a, k))
        self.errors = []
        self.addCleanup(lambda: (setattr(deskwatch, "GH", self.saved[0]), setattr(deskwatch, "sleep", self.saved[1]),
                                 setattr(deskwatch.log, "error", self.saved[2]),
                                 setattr(deskwatch, "GRACE", self.saved[3])))

    def pr(self, n, head=SHA, state="OPEN", mergeable="MERGEABLE", repo=REPO):
        (self.prs / f"{repo.replace('/', '_')}#{n}.json").write_text(
            json.dumps({"state": state, "headRefOid": head, "mergeable": mergeable, "mergeCommit": None}))

    def hand_over(self, n, pinned=SHA, repo=REPO):
        k = f"{repo}#{n}"
        with deskfile.locked():
            deskfile.put_item(k, desk.item_block(repo, n, f"what {n} does", "merge", "CI green", pinned, "dev", None,
                                                 "Faisal", "2026-11-13 10:40"))
            desk.log("ready", k, pinned=pinned)
        return k

    def tick_box(self, n, repo=REPO):
        k = f"{repo}#{n}"
        deskfile.edit(lambda t: t.replace(f"- [ ] Merge {k}:", f"- [x] Merge {k}:"))

    def item(self, n, repo=REPO):
        return next(i for i in deskfile.items() if i.key == f"{repo}#{n}")

    def calls(self):
        f = self.prs / "calls.log"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def merge_calls(self):
        return [c for c in self.calls() if c["args"][:2] == ["pr", "merge"]]

    def events(self, k=None):
        return [r["event"] for r in desk.history(k)]


class Press(Case):
    def test_a_ticked_item_merges_at_its_pinned_commit(self):
        self.pr(272)
        k = self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        self.assertEqual(self.merge_calls()[0]["args"],
                         ["pr", "merge", "272", "-R", REPO, "--merge", "--match-head-commit", SHA])
        it = self.item(272)
        self.assertTrue(it.ticked)
        self.assertRegex(it.block, r"\n  - Merged as 41678e3 at \d\d:\d\d\n")
        self.assertEqual(self.events(k), ["ready", "pressing", "merged"])
        self.assertIn("merged as 41678e3", desk.status_line(k))

    def test_an_unticked_item_is_left_alone(self):
        self.pr(272)
        self.hand_over(272)
        deskwatch.tick()
        self.assertEqual(self.calls(), [])

    def test_the_item_is_found_by_key_and_pin_not_by_position(self):
        self.pr(1, head=SHA)
        self.pr(2, head=SHA2)
        self.hand_over(1, SHA)
        self.hand_over(2, SHA2)
        # the person ticks the second; a third item is put in front of it between ticks
        self.tick_box(2)
        self.pr(3, head="c" * 40)
        deskfile.edit(lambda t: t.replace("## Pull requests waiting for your merge\n",
                                          "## Pull requests waiting for your merge\n" + desk.item_block(
                                              REPO, 3, "front", "merge", "", "c" * 40, "dev", None, "x", "now"), 1))
        deskwatch.tick()
        self.assertEqual([c["args"][2] for c in self.merge_calls()], ["2"])
        self.assertEqual(self.merge_calls()[0]["args"][-1], SHA2)

    def test_an_item_with_a_comment_keeps_its_neighbour_bytes(self):
        self.pr(1)
        self.pr(2, head=SHA2)
        self.hand_over(1)
        self.hand_over(2, SHA2)
        deskfile.edit(lambda t: t.replace("  - Handed over by Faisal, 2026-11-13 10:40.\n",
                                          "  - Handed over by Faisal, 2026-11-13 10:40.\n  <!-- comment c1: wait -->\n", 1))
        before = self.item(1).block
        self.tick_box(2)
        deskwatch.tick()
        self.assertEqual(self.item(1).block, before)
        self.assertIn("<!-- comment c1: wait -->", before)


class Refused(Case):
    def test_a_branch_pushed_after_the_hand_over_is_refused_and_unticks_the_box(self):
        self.pr(272, head=SHA2)                              # pinned SHA, branch is now SHA2
        k = self.hand_over(272, SHA)
        self.tick_box(272)
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        it = self.item(272)
        self.assertFalse(it.ticked)
        self.assertIn("  - Not merged: the branch changed after the review", it.block)
        self.assertEqual(self.events(k), ["ready", "pressing", "refused"])
        self.assertIn("refused: the branch changed after the review", desk.status_line(k))

    def test_a_refused_press_can_be_pressed_again_once_fixed(self):
        self.pr(272, head=SHA2)
        self.hand_over(272, SHA)
        self.tick_box(272)
        deskwatch.tick()
        self.pr(272, head=SHA)                               # the branch is back at the reviewed commit
        self.tick_box(272)
        deskwatch.tick()
        self.assertEqual(len(self.merge_calls()), 1)
        self.assertNotIn("Not merged", self.item(272).block)       # the earlier result is replaced
        self.assertIn("Merged as 41678e3", self.item(272).block)

    def test_a_pr_that_is_not_mergeable_is_refused_with_githubs_word(self):
        self.pr(272, mergeable="CONFLICTING")
        self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        self.assertIn("Not merged: GitHub says CONFLICTING", self.item(272).block)
        self.assertFalse(self.item(272).ticked)

    def test_a_merge_gh_refuses_is_refused_and_says_so(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        (self.prs / "merge-fails").write_text("")
        deskwatch.tick()
        self.assertIn("Not merged: the merge failed: GraphQL: Pull request is not mergeable", self.item(272).block)
        self.assertFalse(self.item(272).ticked)

    def test_a_press_taken_back_during_the_wait_merges_nothing(self):
        self.pr(272, mergeable="MERGEABLE")
        self.hand_over(272)
        self.tick_box(272)
        (self.prs / "unknown-272").write_text("2")
        deskwatch.sleep = lambda s: deskfile.edit(lambda t: t.replace("- [x] Merge", "- [ ] Merge"))
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        self.assertFalse(self.item(272).ticked)
        self.assertNotIn("Not merged", self.item(272).block)

    def test_without_gh_the_press_is_refused(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        deskwatch.GH = None
        deskwatch.tick()
        self.assertIn("Not merged: GitHub could not be asked: gh was not found", self.item(272).block)
        self.assertFalse(self.item(272).ticked)


class Hostile(Case):
    def test_an_already_merged_pr_at_another_commit_is_not_called_merged(self):
        self.pr(272, state="MERGED", head=SHA2)
        self.hand_over(272, SHA)
        self.tick_box(272)
        deskwatch.tick()
        self.assertIn("Not merged: the PR is already merged, but at bbbbbbb", self.item(272).block)
        self.assertFalse(self.item(272).ticked)

    def test_two_items_with_one_key_press_neither_and_do_not_loop(self):
        self.pr(272)
        k = self.hand_over(272)
        self.tick_box(272)
        text = deskfile.items()[0].block
        deskfile.edit(lambda t: t + text.replace("- [x]", "- [ ]"))
        deskwatch.tick()
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        self.assertEqual(self.events(k), ["ready"])
        self.assertEqual(len(self.errors), 1)

    def test_gh_json_with_null_values_is_unreadable_not_a_crash(self):
        self.pr(272, head=None, state=None)
        k = self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        self.assertIn("GitHub could not be asked: GitHub's answer could not be read", self.item(272).block)
        self.assertFalse(self.item(272).ticked)

    def test_a_second_result_replaces_only_our_last_line_not_the_persons_note_above_it(self):
        self.pr(272, head=SHA2)
        self.hand_over(272, SHA)
        self.tick_box(272)
        deskfile.edit(lambda t: t.replace("  - Handed over", "  - Not merged: my own note, please keep\n  - Handed over", 1))
        deskwatch.tick()                                     # refused: our line goes last
        self.pr(272, head=SHA)
        self.tick_box(272)
        deskwatch.tick()
        block = self.item(272).block
        self.assertIn("  - Not merged: my own note, please keep\n", block)
        self.assertNotIn("branch changed", block)
        self.assertRegex(block, r"Merged as 41678e3")


class Unknown(Case):
    def test_unknown_that_clears_within_a_minute_merges(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        (self.prs / "unknown-272").write_text("5")
        deskwatch.tick()
        self.assertEqual(self.sleeps, [2] * 5)
        self.assertEqual(len(self.merge_calls()), 1)
        self.assertIn("Merged as 41678e3", self.item(272).block)

    def test_unknown_that_does_not_clear_is_refused_after_sixty_seconds_and_says_so(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        (self.prs / "unknown-272").write_text("1000")
        deskwatch.tick()
        self.assertEqual(self.sleeps, [2] * 30)
        self.assertEqual(self.merge_calls(), [])
        self.assertIn("Not merged: GitHub still says UNKNOWN after 60 s", self.item(272).block)
        self.assertFalse(self.item(272).ticked)

    def test_a_branch_pushed_while_waiting_is_caught_at_once(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        (self.prs / "unknown-272").write_text("1000")
        pushed = lambda s: self.pr(272, head=SHA2)
        deskwatch.sleep = pushed
        deskwatch.tick()
        self.assertIn("the branch changed after the review", self.item(272).block)
        self.assertEqual(self.merge_calls(), [])


class OneAtATime(Case):
    def merges(self):
        return (self.prs / "merges.log").read_text().split()

    def test_two_presses_merge_one_after_the_other_in_page_order(self):
        for n in (1, 2):
            self.pr(n)
            self.hand_over(n)
            self.tick_box(n)
        deskwatch.tick()
        self.assertEqual(self.merges(), ["start", "1", "end", "1", "start", "2", "end", "2"])

    def test_two_watchers_at_once_press_each_item_once_and_never_together(self):
        for n in (1, 2):
            self.pr(n)
            self.hand_over(n)
            self.tick_box(n)
        threads = [threading.Thread(target=deskwatch.tick) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        deskwatch.tick()
        self.assertEqual(sorted(c["args"][2] for c in self.merge_calls()), ["1", "2"])
        words = self.merges()
        self.assertEqual(words[0::2], ["start", "end", "start", "end"])      # never two starts in a row

    def test_a_merged_item_stays_ticked_and_is_never_pressed_again(self):
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        deskwatch.tick()
        deskwatch.tick()
        self.assertEqual(len(self.merge_calls()), 1)
        self.assertTrue(self.item(272).ticked)


class Restart(Case):
    """The service was restarted under a press: the log says `pressing` and nothing after it."""

    def interrupted(self, n=272):
        k = self.hand_over(n)
        self.tick_box(n)
        deskwatch.record("pressing", k, pinned=SHA)
        return k

    def test_pressing_is_in_the_log_before_the_merge_call_and_merged_after(self):
        self.pr(272)
        k = self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        merge = self.merge_calls()[0]
        self.assertEqual(json.loads(merge["log"][0])["event"], "pressing")
        self.assertEqual(self.events(k)[-1], "merged")

    def test_a_press_with_no_result_that_github_shows_merged_is_recorded_and_never_pressed_again(self):
        self.pr(272, state="MERGED")
        k = self.interrupted()
        deskwatch.tick()
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        self.assertEqual(self.events(k), ["ready", "pressing", "merged"])
        self.assertIn("Already merged", self.item(272).block)

    def test_a_press_with_no_result_that_github_shows_open_is_refused_not_pressed(self):
        self.pr(272)
        k = self.interrupted()
        deskwatch.tick()
        self.assertEqual(self.merge_calls(), [])
        self.assertEqual(self.events(k), ["ready", "pressing", "refused"])
        self.assertFalse(self.item(272).ticked)
        self.assertIn("interrupted", self.item(272).block)

    def test_an_open_pr_is_not_called_unmerged_while_the_press_may_still_be_completing(self):
        self.pr(272)
        k = self.interrupted()
        deskwatch.GRACE = 3600
        deskwatch.tick()
        self.assertEqual(self.events(k), ["ready", "pressing"])
        self.assertTrue(self.item(272).ticked)
        self.assertEqual(self.merge_calls(), [])

    def test_a_pr_merged_at_another_commit_than_the_pinned_one_is_not_blessed(self):
        self.pr(272, state="MERGED", head=SHA2)
        k = self.interrupted()
        deskwatch.tick()
        self.assertEqual(self.events(k), ["ready", "pressing", "refused"])
        self.assertIn("not the reviewed ead9a1f", self.item(272).block)
        self.assertNotIn("Already merged", self.item(272).block)

    def test_github_unreachable_leaves_it_open_and_presses_nothing(self):
        k = self.interrupted()                                # no PR file: gh fails
        deskwatch.tick()
        self.assertEqual(self.events(k), ["ready", "pressing"])
        self.assertEqual(self.merge_calls(), [])
        self.assertTrue(self.item(272).ticked)


class Gh(Case):
    def test_gh_is_the_absolute_path_and_no_path_entry_is_consulted(self):
        self.assertTrue(deskwatch.GH is None or os.path.isabs(deskwatch.GH))
        self.assertNotIn(os.path.expanduser("~/.local/bin"), deskwatch.SYSTEM_PATH)
        decoy = self.tmp / "evil"
        decoy.mkdir()
        (decoy / "gh").write_text(f"#!/bin/sh\ntouch {self.tmp}/decoy-ran\nexit 0\n")
        (decoy / "gh").chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{decoy}:{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        self.pr(272)
        self.hand_over(272)
        self.tick_box(272)
        deskwatch.tick()
        self.assertFalse((self.tmp / "decoy-ran").exists())
        self.assertEqual({c["path"] for c in self.calls()}, {deskwatch.SYSTEM_PATH})
        self.assertEqual(len(self.merge_calls()), 1)

    def test_the_default_gh_is_found_in_the_system_folders_only(self):
        want = shutil_which_system()
        self.assertEqual(self.saved[0], want)


def shutil_which_system():
    return shutil.which("gh", path=deskwatch.SYSTEM_PATH)


class Settle(unittest.TestCase):
    TEXT = ("# Desk\n\n## Pull requests waiting for your merge\n"
            "- [x] Merge a/b#1: one\n  - Pinned commit: " + SHA + "\n  <!-- c1 -->\n\n"
            "- [ ] Merge a/b#2: two\n  - Pinned commit: " + SHA2 + "\n")

    def test_writes_the_result_last_in_the_block_and_unticks(self):
        got = deskfile.settle(self.TEXT, "a/b#1", "Not merged: x", untick=True)
        self.assertIn("- [ ] Merge a/b#1: one\n  - Pinned commit: " + SHA + "\n  <!-- c1 -->\n  - Not merged: x\n\n- [ ] Merge a/b#2", got)

    def test_replaces_an_earlier_result_and_leaves_the_neighbour_alone(self):
        once = deskfile.settle(self.TEXT, "a/b#1", "Not merged: x")
        twice = deskfile.settle(once, "a/b#1", "Merged as abc1234 at 10:00")
        self.assertEqual(twice.count("  - "), 3)
        self.assertNotIn("Not merged", twice)
        self.assertTrue(twice.endswith(self.TEXT.split("\n\n")[-1]))

    def test_no_such_item_changes_nothing(self):
        self.assertEqual(deskfile.settle(self.TEXT, "a/b#9", "x"), self.TEXT)


if __name__ == "__main__":
    unittest.main()
