"""What ships: how the merge desk tells a Deploy item from a Merge item and what it shows under it.

`deskships` is given a `run(*gh_args) -> (exit code, output)` in place of `gh`, which answers from a dict:
no network, no checkout, no GitHub. The classifier is `~/.claude/routines/branch_deploys.py` run on a
folder made of the base branch's workflow files, never on a PR's checkout.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deskships

TESTS_ONLY = "name: ci\non:\n  push:\n    branches: [main]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: pytest\n"
DEPLOYS = "name: deploy\non:\n  push:\n    branches: [main]\njobs:\n  d:\n    runs-on: x\n    steps:\n      - run: ./deploy.sh\n"
PR_ONLY = "name: pr\non:\n  pull_request:\njobs:\n  d:\n    runs-on: x\n    steps:\n      - run: ./deploy.sh\n"


class FakeGh:
    """Answers `gh api` for one repo: workflows by name per ref, a compare per (base, head)."""

    def __init__(self, workflows=None, commits=(), total=None, files=()):
        self.files = list(files)
        self.workflows = workflows
        self.commits = list(commits)
        self.total = len(self.commits) if total is None else total
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        path = next(a for a in args if a.startswith("repos/"))
        if "/contents/.github/workflows" in path:
            ref = path.split("?ref=")[1]
            if ref != "main" or self.workflows is None:
                return 1, "gh: Not Found (HTTP 404)"
            name = path.split("/workflows")[1].split("?")[0].lstrip("/")
            if not name:
                return 0, json.dumps([{"name": n, "type": "file"} for n in self.workflows])
            return (0, self.workflows[name]) if name in self.workflows else (1, "gh: Not Found (HTTP 404)")
        if "/compare/" in path:
            return 0, json.dumps({"total_commits": self.total, "files": [{"filename": f} for f in self.files], "commits": [
                {"sha": s, "commit": {"message": m + "\n\nbody"}} for s, m in self.commits]})
        return 1, "unexpected " + path


class Classify(unittest.TestCase):
    def test_a_repo_whose_workflows_only_test_ships_nothing(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")])
        self.assertEqual(deskships.read("o/r", "main", "p" * 40, gh), [])

    def _long(self, run):
        return DEPLOYS.replace("./deploy.sh", run)

    def _run_of_width(self, width):
        return "./deploy.sh && " + "x" * (width - len("- run: ./deploy.sh && "))          # the width of the whole line

    def _lines(self, run):
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"deploy.yml": self._long(run)}, [("a" * 40, "x")]))
        return got, [l for l in got if l.startswith("  - deploy.yml:9: ")]

    def test_a_deploy_line_longer_than_any_cut_is_still_listed_and_names_its_digest(self):
        for width in (139, 140, 141, 155, 400, 5000):
            with self.subTest(width=width):
                got, lines = self._lines(self._run_of_width(width))
                self.assertEqual(got[0], "- Fires on push to main: deploy.yml")
                self.assertEqual(len(lines), 1, got)
                self.assertLessEqual(len(lines[0]), 4 + 180)
                self.assertEqual("sha256:" in lines[0], len("deploy.yml:9: ") + width > 180, lines[0])

    def test_a_change_after_the_cut_is_a_change(self):
        for width in (141, 155, 400):
            with self.subTest(width=width):
                old = self._lines(self._run_of_width(width))[0]
                new = self._lines(self._run_of_width(width - 1) + "y")[0]
                self.assertEqual(deskships.changed(old, old), "")
                self.assertNotEqual(deskships.changed(old, new), "")

    def test_a_change_of_one_space_or_a_no_break_space_after_the_cut_is_a_change(self):
        base = self._run_of_width(300)
        old = self._lines(base)[0]
        for new_run in (base.replace("xx", "x x", 1), base.replace("xx", "x\u00a0x", 1), base.replace("&& ", "&&  ", 1)):
            with self.subTest(run=new_run[:30]):
                self.assertNotEqual(deskships.changed(old, self._lines(new_run)[0]), "")

    def test_a_short_line_that_the_page_would_fold_is_compared_unfolded(self):
        run = "./deploy.sh  --env prod"
        old = self._lines(run)[0]
        self.assertNotEqual(deskships.changed(old, self._lines(run.replace("  ", " "))[0]), "")
        self.assertNotEqual(deskships.changed(old, self._lines(run.replace("  ", "\u00a0 "))[0]), "")

    def test_a_long_list_of_workflows_is_listed_not_refused(self):
        flows = {f"deploy-{i:03}-" + "x" * 20 + ".yml": DEPLOYS for i in range(20)}
        got = deskships.read("o/r", "main", "p" * 40, FakeGh(flows, [("a" * 40, "x")]))
        self.assertTrue(got[0].startswith("- Fires on push to main: deploy-000-"), got[0])
        self.assertIn("sha256:", got[0])
        self.assertNotIn("Could not tell", "\n".join(got))
        changed = dict(flows, **{"deploy-019-" + "x" * 20 + ".yml": DEPLOYS.replace("./deploy.sh", "./other.sh")})
        again = deskships.read("o/r", "main", "p" * 40, FakeGh(changed, [("a" * 40, "x")]))
        self.assertNotEqual(deskships.changed(got, again), "")

    def _tell(self, got):
        return [l for l in got if l.startswith("- Could not tell what ships:")]

    def test_a_workflow_that_cannot_be_parsed_is_could_not_tell_and_names_the_file(self):
        for text in ("on: [push\njobs: {\n", "on: push\njobs:\n  d:\n    steps: [a, b\n", "\tname: x\non: push\n"):
            with self.subTest(text=text):
                got = deskships.read("o/r", "main", "p" * 40, FakeGh({"ci.yml": TESTS_ONLY, "broken.yml": text}, [("a" * 40, "x")]))
                tell = self._tell(got)
                self.assertEqual(len(tell), 1, got)
                self.assertIn("broken.yml", tell[0])
                self.assertIn("could not be parsed", tell[0])
                self.assertNotIn("ci.yml", tell[0])
                self.assertNotIn("- Fires on push to main: broken.yml", got)

    def test_a_workflow_that_cannot_be_parsed_and_has_a_deploy_word_is_could_not_tell_too(self):
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"b.yml": "on: [push\n# x\nrun: ./deploy.sh\n  bad: [\n"}, [("a" * 40, "x")]))
        self.assertEqual(len(self._tell(got)), 1, got)

    def test_a_press_cannot_pass_a_workflow_it_could_not_parse(self):
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"b.yml": "on: [push\njobs: {\n"}, [("a" * 40, "x")]))
        self.assertIn("could not tell", deskships.changed(got, got).lower())

    def test_every_could_not_tell_says_what_the_person_can_do(self):
        saved = deskships.CLASSIFIER
        self.addCleanup(setattr, deskships, "CLASSIFIER", saved)
        deskships.CLASSIFIER = Path("/nonexistent/branch_deploys.py")
        missing = deskships.read("o/r", "main", "p" * 40, FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")]))
        deskships.CLASSIFIER = saved
        broken = deskships.read("o/r", "main", "p" * 40, FakeGh({"b.yml": "on: [push\n"}, [("a" * 40, "x")]))
        cut = deskships.read("o/r", "main", "p" * 40, FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")], files=[f"f{i}" for i in range(300)]))
        for got in (missing, broken, cut):
            tell = self._tell(got)
            self.assertEqual(len(tell), 1, got)
            self.assertIn("merge it on GitHub yourself", tell[0])
            self.assertIn("ask the session to", tell[0])
            self.assertIn("split the pull request", tell[0])

    def test_a_deploy_line_that_fits_under_both_cuts_is_listed_whole(self):
        run = "./deploy.sh && " + "x" * (130 - len("- run: ./deploy.sh && "))
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"deploy.yml": self._long(run)}, [("a" * 40, "x")]))
        self.assertEqual(got[0], "- Fires on push to main: deploy.yml")
        self.assertTrue(got[2].endswith(run), got)

    def test_a_press_cannot_pass_a_line_it_could_not_check(self):
        old = ["- Could not tell what ships: the classifier did not run"]
        self.assertIn("could not tell", deskships.changed(old, old).lower())

    def test_a_repo_with_no_workflows_at_all_ships_nothing(self):
        self.assertEqual(deskships.read("o/r", "main", "p" * 40, FakeGh(None)), [])

    def test_a_deploy_workflow_lists_its_lines_and_the_commits_that_go_out(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY, "deploy.yml": DEPLOYS},
                    [("abc1234" + "0" * 33, "Fix the thing"), ("def5678" + "0" * 33, "Add the other")])
        got = deskships.read("o/r", "main", "p" * 40, gh)
        self.assertEqual(got[0], "- Fires on push to main: deploy.yml")
        self.assertTrue(any("./deploy.sh" in l and l.startswith("  - ") for l in got))
        self.assertNotIn("ci.yml", " ".join(got))
        self.assertIn("- Commits that go out (2):", got)
        self.assertIn("  - abc1234 Fix the thing", got)
        self.assertIn("  - def5678 Add the other", got)

    def test_a_workflow_that_does_not_run_on_a_push_to_the_base_ships_nothing(self):
        self.assertEqual(deskships.read("o/r", "main", "p" * 40, FakeGh({"pr.yml": PR_ONLY})), [])

    def test_the_classifier_sees_only_the_base_branchs_workflows_never_the_pull_request(self):
        gh = FakeGh({"deploy.yml": DEPLOYS})
        deskships.read("o/r", "main", "p" * 40, gh)
        refs = {a.split("?ref=")[1] for c in gh.calls for a in c if "/contents/" in a}
        self.assertEqual(refs, {"main"})

    def test_a_ships_line_from_the_person_comes_first_and_the_commits_follow(self):
        gh = FakeGh(None, [("abc1234" + "0" * 33, "One")])
        got = deskships.read("o/r", "main", "p" * 40, gh, outside="the daily t-compute run uses main")
        self.assertEqual(got[0], "- Outside GitHub: the daily t-compute run uses main")
        self.assertEqual(got[-2:], ["- Commits that go out (1):", "  - abc1234 One"])

    def test_an_unreadable_workflow_listing_is_an_error_not_a_merge(self):
        with self.assertRaises(deskships.Unreadable):
            deskships.read("o/r", "main", "p" * 40, lambda *a: (1, "gh: HTTP 502"))

    def test_a_missing_classifier_makes_the_item_a_deploy_that_says_so(self):
        saved = deskships.CLASSIFIER
        deskships.CLASSIFIER = Path("/nonexistent/branch_deploys.py")
        self.addCleanup(setattr, deskships, "CLASSIFIER", saved)
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")]))
        self.assertIn("Could not tell what ships", got[0])

    def test_a_workflow_name_that_climbs_out_of_the_folder_is_not_written(self):
        gh = FakeGh({"../evil.yml": DEPLOYS, "ci.yml": TESTS_ONLY})
        with self.assertRaises(deskships.Unreadable):
            deskships.read("o/r", "main", "p" * 40, gh)
        self.assertFalse(any("evil" in a for c in gh.calls for a in c if "/contents/.github/workflows/" in a))

    def test_commit_messages_cannot_open_a_box_or_a_second_line(self):
        gh = FakeGh({"deploy.yml": DEPLOYS}, [("abc1234" + "0" * 33, "x [ ] <!-- y")])
        got = deskships.read("o/r", "main", "p" * 40, gh)
        line = next(l for l in got if "Fix" in l or l.startswith("  - abc1234"))
        self.assertNotIn("[ ]", line)
        self.assertNotIn("<!--", line)

    def test_more_commits_than_shown_are_counted(self):
        commits = [(f"{i:07x}" + "0" * 33, f"c{i}") for i in range(130)]
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"deploy.yml": DEPLOYS}, commits, total=130))
        self.assertIn("- Commits that go out (130):", got)
        self.assertEqual(got[-1], "  - and 30 more")


class Hardening(unittest.TestCase):
    def test_a_pr_that_adds_a_workflow_is_a_deploy_because_the_merge_runs_the_merged_files(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")], files=["src/a.py", ".github/workflows/release.yml"])
        got = deskships.read("o/r", "main", "p" * 40, gh)
        self.assertIn("- This pull request changes workflow files:", got)
        self.assertIn("  - .github/workflows/release.yml", got)

    def test_a_file_list_cut_by_github_is_not_read_as_no_workflow_change(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")], files=[f"f{i}" for i in range(300)])
        self.assertIn("Could not tell what ships", "\n".join(deskships.read("o/r", "main", "p" * 40, gh)))

    def test_a_classifier_that_crashes_is_not_nothing_ships(self):
        import tempfile
        bad = Path(tempfile.mkdtemp()) / "bd.py"
        bad.write_text("raise SystemExit(1) if False else None\nimport nonexistent_module_x\n")
        saved = deskships.CLASSIFIER
        deskships.CLASSIFIER = bad
        self.addCleanup(setattr, deskships, "CLASSIFIER", saved)
        got = deskships.read("o/r", "main", "p" * 40, FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")]))
        self.assertIn("Could not tell what ships", got[0])

    def test_a_compare_answer_without_files_is_unreadable(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")])
        real = gh.__call__

        def no_files(*a):
            code, out = real(*a)
            if "/compare/" in " ".join(a):
                out = json.dumps({k: v for k, v in json.loads(out).items() if k != "files"})
            return code, out
        with self.assertRaises(deskships.Unreadable):
            deskships.read("o/r", "main", "p" * 40, no_files)

    def test_a_workflow_with_a_name_that_cannot_be_fetched_safely_is_an_error_not_skipped(self):
        with self.assertRaises(deskships.Unreadable):
            deskships.read("o/r", "main", "p" * 40, FakeGh({"my deploy.yml": DEPLOYS}))


class Differ(unittest.TestCase):
    def test_commits_are_compared_by_sha_only_so_a_page_that_rewrote_the_message_is_no_change(self):
        old = ["- Commits that go out (1):", "  - aaaaaaa **init** fix"]
        new = ["- Commits that go out (1):", "  - aaaaaaa __init__ fix"]
        self.assertEqual(deskships.changed(old, new), "")

    def test_a_range_that_was_cut_at_hand_over_is_not_compared_after_the_parent_merged(self):
        old = ["- Commits that go out (40):", "  - 0000001 a", "  - and 10 more"]
        new = ["- Commits that go out (10):", "  - 0000031 z"]
        self.assertEqual(deskships.changed(old, new), "")

    def test_workflow_files_that_left_the_range_are_not_a_change_but_a_new_one_is(self):
        head = "- This pull request changes workflow files:"
        old = [head, "  - .github/workflows/a.yml", "  - .github/workflows/_shared_.yml"]
        self.assertEqual(deskships.changed(old, []), "")
        self.assertIn("c.yml", deskships.changed(old, [head, "  - .github/workflows/c.yml"]))

    def test_a_could_not_tell_answer_now_is_always_a_change(self):
        both = ["- Could not tell what ships: the classifier is missing"]
        self.assertIn("could not tell", deskships.changed(both, both).lower())

    def test_a_changed_operator_is_a_change(self):
        old = ["- Fires on push to main: deploy.yml", "  - deploy.yml:7: run: test -f x && ./deploy.sh"]
        new = ["- Fires on push to main: deploy.yml", "  - deploy.yml:7: run: test -f x || ./deploy.sh"]
        self.assertIn("||", deskships.changed(old, new))

    def test_many_workflow_files_are_each_on_a_line_of_their_own(self):
        gh = FakeGh({"ci.yml": TESTS_ONLY}, [("a" * 40, "x")], files=[f".github/workflows/w{i:03}.yml" for i in range(60)])
        got = deskships.read("o/r", "main", "p" * 40, gh)
        self.assertEqual(sum(1 for l in got if l.startswith("  - .github/workflows/w")), 60)

    def _line_change(self, old, new):
        head = "- Fires on push to main: deploy.yml"
        return deskships.changed([head, "  - " + old], [head, "  - " + new])

    def test_the_stored_lines_are_compared_exactly_not_after_stripping(self):
        for old, new in [
            ("run: ./deploy_prod.sh", "run: ./deployprod.sh"),
            ("--env=prod_eu", "--env=prodeu"),
            ("${{ secrets.DEPLOY_KEY_PROD }}", "${{ secrets.DEPLOYKEY_PROD }}"),
            ("run: echo `./deploy.sh`", "run: echo ./deploy.sh"),
            ("rsync dist/* host:/srv", "rsync dist/ host:/srv"),
            ("./build.sh < in.txt; ./deploy.sh --target prod > out.log", "./build.sh < in.txt; ./deploy.sh --target staging-eu > out.log"),
            ("./deploy.sh <in --target prod >out.log", "./deploy.sh <in --target staging >out.log"),
            ("run: echo \\$TOKEN", "run: echo $TOKEN"),
            ("cat <prod>out", "cat <dev>out"),
            ("run: ./deploy.sh", "run: ./deploy.sh <prod>"),
            ("rm -rf dist/_", "rm -rf dist/*"),
            ("x && y", "x \\&& y"),
            ("run: ./__init__.sh", "run: ./**init**.sh"),
        ]:
            with self.subTest(old=old, new=new):
                self.assertNotEqual(self._line_change(old, new), "")

    def test_the_same_raw_line_is_no_change_whatever_it_holds(self):
        for line in ["run: ./deploy.sh <staging>", "run: ./a_b.sh \\* <https://x.y> `z`", "cat <in --x >out", "a  b"]:
            with self.subTest(line=line):
                self.assertEqual(self._line_change(line, line), "")

    def test_commits_that_dropped_out_of_the_range_are_not_a_change(self):
        old = ["- Fires on push to main: deploy.yml", "- Commits that go out (2):", "  - aaaaaaa One", "  - bbbbbbb Two"]
        new = ["- Fires on push to main: deploy.yml", "- Commits that go out (1):", "  - bbbbbbb Two"]
        self.assertEqual(deskships.changed(old, new), "")

    def test_a_commit_that_is_new_is_a_change(self):
        old = ["- Commits that go out (1):", "  - aaaaaaa One"]
        new = ["- Commits that go out (2):", "  - aaaaaaa One", "  - ccccccc Three"]
        self.assertIn("commit ccccccc Three", deskships.changed(old, new))

    def test_what_changed_is_named(self):
        old = ["- Fires on push to main: deploy.yml", "  - 7: run: ./deploy.sh", "- Commits that go out (1):", "  - aaaaaaa One"]
        new = ["- Fires on push to main: deploy.yml", "  - 7: run: ./deploy.sh && ./more.sh", "- Commits that go out (1):", "  - aaaaaaa One"]
        why = deskships.changed(old, new)
        self.assertIn("./more.sh", why)
        self.assertEqual(deskships.changed(old, old), "")

    def test_the_outside_line_is_the_persons_and_not_compared(self):
        old = ["- Outside GitHub: the daily run", "- Commits that go out (1):", "  - aaaaaaa One"]
        self.assertEqual(deskships.changed(old, old[1:]), "")


if __name__ == "__main__":
    unittest.main()
