"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, built only from a hub that already runs.

`sheaf` is never run here: a fake answers `status` and `open` the way sheaf
1.0.3 prints them, and records what was asked. The refresh that asks it runs
inline (`start`), except where a test is about the poll not waiting for it.
The pm folder is a temp dir; the clock is passed in. Names are invented.
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


LISTED = "  http://127.0.0.1:{port}/claude/pm/{name}\n    {file} \u00b7 1 tab open\n"


class Sheaf:
    """A fake `sheaf`: a hub on `port`, or none when `port` is None; `rendered`
    are the goal files it lists as rendered since it started."""
    def __init__(self, port=27419, open_fails=False, rendered=()):
        self.port, self.open_fails, self.asked = port, open_fails, []
        self.rendered = list(rendered)

    def __call__(self, args):
        self.asked.append(args)
        if args[0] == "status":
            return (0, STATUS.format(port=self.port)) if self.port else (1, "  no hub is running\n")
        if args[0] == "list":
            if self.port is None:
                return 0, "  no hub is running\n"
            return 0, "".join(LISTED.format(port=self.port, name=Path(f).name, file=f) for f in self.rendered) \
                or "  nothing has been rendered since the hub started\n"
        if args[0] == "open":
            if self.port is None:
                raise AssertionError("sheaf open with no hub: that starts one")
            if self.open_fails:
                return 1, ""
            return 0, OPEN.format(port=self.port, name=Path(args[1]).name)
        raise AssertionError(f"unexpected sheaf {args}")

    def opened(self):
        return [a for a in self.asked if a[0] == "open"]


def inline(work):
    work()


def of(track, now, run):
    return goal_page.of(track, now=now, run=run, start=inline)


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
        got = of("checkout", now=100, run=sheaf)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})
        self.assertEqual(sheaf.opened(), [["open", str(self.pm / "checkout.goal.md"), "--no-browser"]])

    def test_with_no_hub_the_link_says_so_and_no_hub_is_started(self):
        sheaf = Sheaf(port=None)
        got = of("checkout", now=100, run=sheaf)
        self.assertIsNone(got["url"])
        self.assertIn("no sheaf hub", got["why"])
        self.assertEqual(sheaf.opened(), [])

    def test_the_port_is_the_running_hubs_even_when_open_prints_another(self):
        sheaf = Sheaf(port=31000)
        real = sheaf.__call__
        sheaf_run = lambda args: (0, OPEN.format(port=1, name="checkout.goal.md")) if args[0] == "open" else real(args)
        got = of("checkout", now=100, run=sheaf_run)
        self.assertEqual(got["url"], "http://127.0.0.1:31000/claude/pm/checkout.goal.md")

    def test_a_track_with_no_goal_file_has_no_link(self):
        sheaf = Sheaf()
        self.assertIsNone(of("docs", now=100, run=sheaf))
        self.assertEqual(sheaf.opened(), [])

    def test_only_a_name_a_track_can_have_is_looked_up(self):
        (self.pm.parent / "secret.goal.md").write_text("x")
        sheaf = Sheaf()
        self.assertIsNone(of("../secret", now=100, run=sheaf))
        self.assertEqual(sheaf.asked, [])

    def test_when_sheaf_cannot_open_the_goal_the_link_says_so(self):
        got = of("checkout", now=100, run=Sheaf(open_fails=True))
        self.assertIsNone(got["url"])
        self.assertIn("could not", got["why"])

    def test_with_no_sheaf_installed_the_link_says_so(self):
        was, goal_page.SHEAF = goal_page.SHEAF, str(self.pm / "no-such-sheaf")
        self.addCleanup(setattr, goal_page, "SHEAF", was)
        got = goal_page.of("checkout", now=100, start=inline)
        self.assertIsNone(got["url"])
        self.assertEqual(got["why"], goal_page.NO_SHEAF)

    def test_the_poll_never_waits_for_sheaf_and_one_refresh_runs_at_a_time(self):
        sheaf, started = Sheaf(), []
        for now in (100, 101):
            got = goal_page.of("checkout", now=now, run=sheaf, start=started.append)
            self.assertEqual(got, {"url": None, "why": goal_page.ASKING})
        self.assertEqual((sheaf.asked, len(started)), ([], 1))
        started[0]()
        got = goal_page.of("checkout", now=102, run=sheaf, start=started.append)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/checkout.goal.md")
        self.assertEqual(len(started), 1)

    def test_a_second_goal_asked_for_later_is_opened_after_a_status_of_its_own(self):
        (self.pm / "docs.goal.md").write_text("## Done when\n- [ ] one\n")
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        got = of("docs", now=101, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/docs.goal.md")
        self.assertEqual([a[0] for a in sheaf.asked], ["status", "list", "open", "status", "list", "open"])

    def test_a_hub_stopped_since_the_last_status_is_not_started_for_a_new_goal(self):
        (self.pm / "docs.goal.md").write_text("## Done when\n- [ ] one\n")
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        sheaf.port = None                       # `sheaf stop`, well within STATUS_EVERY
        got = of("docs", now=101, run=sheaf)
        self.assertEqual(got, {"url": None, "why": goal_page.NO_HUB})
        self.assertEqual(len(sheaf.opened()), 1)

    def test_a_goal_the_hub_has_rendered_is_read_from_its_list_and_not_opened_again(self):
        # An open records its settings anew: a title or theme the page was given would go.
        goal = self.pm / "checkout.goal.md"
        sheaf = Sheaf(rendered=[str(goal.resolve())])
        got = of("checkout", now=100, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/checkout.goal.md")
        self.assertEqual(sheaf.opened(), [])

    def test_a_thread_that_cannot_start_leaves_the_poll_answering_and_the_next_poll_trying(self):
        def no_thread(work):
            raise RuntimeError("can't start new thread")
        sheaf = Sheaf()
        self.assertEqual(goal_page.of("checkout", now=100, run=sheaf, start=no_thread),
                         {"url": None, "why": goal_page.ASKING})
        got = of("checkout", now=101, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/checkout.goal.md")

    def test_the_hub_is_asked_once_a_while_and_a_goal_opened_once_per_hub(self):
        sheaf = Sheaf()
        for now in (100, 110, 120):
            of("checkout", now=now, run=sheaf)
        self.assertEqual([a[0] for a in sheaf.asked], ["status", "list", "open"])
        of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual([a[0] for a in sheaf.asked], ["status", "list", "open", "status"])

    def test_a_hub_that_comes_back_on_another_port_opens_the_goal_again(self):
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        sheaf.port = 27500
        got = of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27500/claude/pm/checkout.goal.md")
        self.assertEqual(len(sheaf.opened()), 2)

    def test_a_hub_gone_since_the_last_look_is_not_started_again(self):
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        sheaf.port = None
        got = of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertIsNone(got["url"])
        self.assertEqual(len(sheaf.opened()), 1)

    def test_an_answer_of_open_that_is_no_page_of_this_hub_is_no_link(self):
        for printed in ("", "  http://example.com/claude/pm/checkout.goal.md\n",
                        '  http://127.0.0.1:27419/claude/pm/"><script>.md\n'):
            with self.subTest(printed=printed):
                goal_page.forget()
                run = lambda args, p=printed: (0, p) if args[0] == "open" else Sheaf()(args)
                self.assertIsNone(of("checkout", now=100, run=run)["url"])


if __name__ == "__main__":
    unittest.main()
