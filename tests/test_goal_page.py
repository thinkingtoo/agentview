"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, built only from a hub that already runs.

`sheaf` is never run here: a fake answers `status` and `open` the way sheaf
1.0.3 prints them, and records what was asked. The pm folder is a temp dir;
the clock is passed in. Names are invented.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import goal_page
import projects

STATUS = ("  hub running on 127.0.0.1:{port}\n    version  1.0.3\n    pid      4242\n"
          "    started  2026-11-10T09:00:00+0100\n    service  no\n")
OPEN = ("  http://127.0.0.1:{port}/claude/pm/{name}\n"
        "  (not opened: the browser is off, by --no-browser, SHEAF_NO_BROWSER or config.toml)\n")


class Sheaf:
    """A fake `sheaf`: a hub on `port`, or none when `port` is None."""
    def __init__(self, port=27419, open_fails=False):
        self.port, self.open_fails, self.asked = port, open_fails, []

    def __call__(self, args):
        self.asked.append(args)
        if args[0] == "status":
            return (0, STATUS.format(port=self.port)) if self.port else (1, "  no hub is running\n")
        if args[0] == "open":
            if self.port is None:
                raise AssertionError("sheaf open with no hub: that starts one")
            if self.open_fails:
                return 1, ""
            return 0, OPEN.format(port=self.port, name=Path(args[1]).name)
        raise AssertionError(f"unexpected sheaf {args}")

    def opened(self):
        return [a for a in self.asked if a[0] == "open"]


class GoalPage(unittest.TestCase):
    def setUp(self):
        self.pm = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pm, True)
        projects.pm_dir, was = (lambda: self.pm), projects.pm_dir
        self.addCleanup(setattr, projects, "pm_dir", was)
        goal_page.forget()
        self.addCleanup(goal_page.forget)
        (self.pm / "checkout.goal.md").write_text("# Objective\n_Status: OPEN_\n\n## Done when\n- [ ] one\n")

    def test_with_a_hub_running_the_link_is_its_page_of_the_goal_file(self):
        sheaf = Sheaf()
        got = goal_page.of("checkout", now=100, run=sheaf)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})
        self.assertEqual(sheaf.opened(), [["open", str(self.pm / "checkout.goal.md"), "--no-browser"]])

    def test_with_no_hub_the_link_says_so_and_no_hub_is_started(self):
        sheaf = Sheaf(port=None)
        got = goal_page.of("checkout", now=100, run=sheaf)
        self.assertIsNone(got["url"])
        self.assertIn("no sheaf hub", got["why"])
        self.assertEqual(sheaf.opened(), [])

    def test_the_port_is_the_running_hubs_even_when_open_prints_another(self):
        sheaf = Sheaf(port=31000)
        real = sheaf.__call__
        sheaf_run = lambda args: (0, OPEN.format(port=1, name="checkout.goal.md")) if args[0] == "open" else real(args)
        got = goal_page.of("checkout", now=100, run=sheaf_run)
        self.assertEqual(got["url"], "http://127.0.0.1:31000/claude/pm/checkout.goal.md")

    def test_a_track_with_no_goal_file_has_no_link(self):
        sheaf = Sheaf()
        self.assertIsNone(goal_page.of("docs", now=100, run=sheaf))
        self.assertEqual(sheaf.opened(), [])

    def test_only_a_name_a_track_can_have_is_looked_up(self):
        (self.pm.parent / "secret.goal.md").write_text("x")
        sheaf = Sheaf()
        self.assertIsNone(goal_page.of("../secret", now=100, run=sheaf))
        self.assertEqual(sheaf.asked, [])

    def test_when_sheaf_cannot_open_the_goal_the_link_says_so(self):
        got = goal_page.of("checkout", now=100, run=Sheaf(open_fails=True))
        self.assertIsNone(got["url"])
        self.assertIn("could not", got["why"])

    def test_with_no_sheaf_installed_the_link_says_so(self):
        def missing(args):
            raise FileNotFoundError("sheaf")
        got = goal_page.of("checkout", now=100, run=missing)
        self.assertIsNone(got["url"])
        self.assertIn("no sheaf hub", got["why"])

    def test_the_hub_is_asked_once_a_while_and_a_goal_opened_once_per_hub(self):
        sheaf = Sheaf()
        for now in (100, 110, 120):
            goal_page.of("checkout", now=now, run=sheaf)
        self.assertEqual([a[0] for a in sheaf.asked], ["status", "open"])
        goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual([a[0] for a in sheaf.asked], ["status", "open", "status"])

    def test_a_hub_that_comes_back_on_another_port_opens_the_goal_again(self):
        sheaf = Sheaf()
        goal_page.of("checkout", now=100, run=sheaf)
        sheaf.port = 27500
        got = goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27500/claude/pm/checkout.goal.md")
        self.assertEqual(len(sheaf.opened()), 2)

    def test_a_hub_gone_since_the_last_look_is_not_started_again(self):
        sheaf = Sheaf()
        goal_page.of("checkout", now=100, run=sheaf)
        sheaf.port = None
        got = goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertIsNone(got["url"])
        self.assertEqual(len(sheaf.opened()), 1)

    def test_an_answer_of_open_that_is_no_page_of_this_hub_is_no_link(self):
        for printed in ("", "  http://example.com/claude/pm/checkout.goal.md\n",
                        '  http://127.0.0.1:27419/claude/pm/"><script>.md\n'):
            with self.subTest(printed=printed):
                goal_page.forget()
                run = lambda args, p=printed: (0, p) if args[0] == "open" else Sheaf()(args)
                self.assertIsNone(goal_page.of("checkout", now=100, run=run)["url"])


if __name__ == "__main__":
    unittest.main()
