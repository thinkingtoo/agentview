"""Where a track's goal opens as a page: the sheaf hub's URL of
`<pm>/<track>.goal.md`, built from a hub that already runs and the roots sheaf
keeps, without ever rendering anything.

`sheaf` is never run here: a fake answers `status` the way sheaf 1.0.3 prints
it, records what was asked and fails on anything else (an `open` would start a
hub, or wipe a page's settings). `roots.json` is a temp file. The refresh that
asks sheaf runs inline (`start`), except where a test is about the poll not
waiting for it. The clock is passed in. Names are invented.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import goal_page
import projects

STATUS = ("  hub running on 127.0.0.1:{port}\n    version  1.0.3\n    pid      4242\n"
          "    started  2026-11-10T09:00:00+0100\n    service  no\n")


class Sheaf:
    """A fake `sheaf`: a hub on `port`, or none when `port` is None."""
    def __init__(self, port=27419):
        self.port, self.asked = port, []

    def __call__(self, args):
        self.asked.append(args)
        if args == ["status"]:
            return (0, STATUS.format(port=self.port)) if self.port else (1, "  no hub is running\n")
        raise AssertionError(f"sheaf {args} must never run: only status is asked")


class Binder(Sheaf):
    """A fake `sheaf` that also lets `open` run, once, for a bind: it records the arguments and the
    environment it was given, and answers `code`."""
    def __init__(self, port=27419, code=0):
        super().__init__(port)
        self.opened, self.code = [], code

    def __call__(self, args, env=None):
        if args[:1] == ["open"]:
            self.opened.append((args, env))
            return self.code, ""
        return super().__call__(args)


def inline(work):
    work()


def of(track, now, run):
    return goal_page.of(track, now=now, run=run, start=inline)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.disk = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.disk, True)
        self.home = self.disk / "dot-claude"             # a config folder that is a git repository
        (self.home / ".git").mkdir(parents=True)
        self.pm = self.home / "pm"
        self.pm.mkdir()
        projects.pm_dir, was = (lambda: self.pm), projects.pm_dir
        self.addCleanup(setattr, projects, "pm_dir", was)
        self.roots = self.disk / "state" / "sheaf" / "roots.json"
        self.roots.parent.mkdir(parents=True)
        goal_page.roots_file, kept = (lambda: self.roots), goal_page.roots_file
        self.addCleanup(setattr, goal_page, "roots_file", kept)
        self.registered(claude=(self.home, True))
        goal_page.forget()
        self.addCleanup(goal_page.forget)
        (self.pm / "checkout.goal.md").write_text("# Objective\n_Status: OPEN_\n\n## Done when\n- [ ] one\n")

    def registered(self, **roots):
        self.roots.write_text(json.dumps({name: {"path": str(path), "git": git, "id": "0" * 16}
                                          for name, (path, git) in roots.items()}))


class GoalPage(Fixture):
    def test_with_a_hub_running_the_link_is_its_page_of_the_goal_and_only_status_is_asked(self):
        sheaf = Sheaf()
        got = of("checkout", now=100, run=sheaf)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})
        self.assertEqual(sheaf.asked, [["status"]])

    def test_with_no_hub_the_link_says_so_and_no_hub_is_started(self):
        sheaf = Sheaf(port=None)
        got = of("checkout", now=100, run=sheaf)
        self.assertEqual(got, {"url": None, "why": goal_page.NO_HUB})
        self.assertEqual(sheaf.asked, [["status"]])

    def test_a_goal_whose_root_sheaf_has_not_registered_has_no_page_yet(self):
        self.registered()
        got = of("checkout", now=100, run=Sheaf())
        self.assertEqual(got, {"url": None, "why": goal_page.NO_ROOT})

    def test_the_root_of_a_goal_in_a_repository_is_its_top_and_not_a_root_outside(self):
        # sheaf's rule 1: the top of the git work tree. A root above it does not hold the goal.
        self.registered(disk=(self.disk, False))
        self.assertEqual(of("checkout", now=100, run=Sheaf())["why"], goal_page.NO_ROOT)

    def test_outside_a_repository_the_deepest_root_that_is_no_repository_holds_the_goal(self):
        shutil.rmtree(self.home / ".git")
        self.registered(disk=(self.disk, False), config=(self.home, False))
        got = of("checkout", now=100, run=Sheaf())
        self.assertEqual(got["url"], "http://127.0.0.1:27419/config/pm/checkout.goal.md")

    def test_every_segment_of_the_address_is_percent_encoded(self):
        shutil.rmtree(self.home / ".git")
        notes = self.disk / "my notes é"
        notes.mkdir()
        (self.pm / "checkout.goal.md").rename(notes / "checkout.goal.md")
        projects.pm_dir = lambda: notes
        self.registered(disk=(self.disk, False))
        got = of("checkout", now=100, run=Sheaf())
        self.assertEqual(got["url"], "http://127.0.0.1:27419/disk/my%20notes%20%C3%A9/checkout.goal.md")

    def test_roots_that_cannot_be_read_give_no_page_and_raise_nothing(self):
        for text in ("", "not json", "[]", '{"claude": "x"}', '{"claude": {"path": "relative"}}'):
            with self.subTest(text=text):
                goal_page.forget()
                self.roots.write_text(text)
                self.assertEqual(of("checkout", now=100, run=Sheaf())["why"], goal_page.NO_ROOT)

    def test_a_root_whose_path_no_file_can_have_is_skipped_and_the_others_still_give_pages(self):
        # A NUL in a path: os.path.realpath raises ValueError on it.
        self.registered(claude=(self.home, True), odd=("/a\x00b", False))
        got = of("checkout", now=100, run=Sheaf())
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/checkout.goal.md")

    def test_the_port_is_the_running_hubs(self):
        got = of("checkout", now=100, run=Sheaf(port=31000))
        self.assertEqual(got["url"], "http://127.0.0.1:31000/claude/pm/checkout.goal.md")

    def test_a_track_with_no_goal_file_has_no_link(self):
        sheaf = Sheaf()
        self.assertIsNone(of("docs", now=100, run=sheaf))
        self.assertEqual(sheaf.asked, [])

    def test_only_a_name_a_track_can_have_is_looked_up(self):
        (self.pm.parent / "secret.goal.md").write_text("x")
        sheaf = Sheaf()
        self.assertIsNone(of("../secret", now=100, run=sheaf))
        self.assertEqual(sheaf.asked, [])

    def test_with_no_sheaf_installed_the_link_says_so(self):
        was, goal_page.SHEAF = goal_page.SHEAF, str(self.disk / "no-such-sheaf")
        self.addCleanup(setattr, goal_page, "SHEAF", was)
        got = goal_page.of("checkout", now=100, start=inline)
        self.assertEqual(got, {"url": None, "why": goal_page.NO_SHEAF})

    def test_an_answer_that_cannot_be_read_is_said_and_asked_again_only_after_a_while(self):
        asked = []
        def garbled(args):
            asked.append(args)
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        self.assertEqual(of("checkout", now=100, run=garbled), {"url": None, "why": goal_page.UNREADABLE})
        of("checkout", now=110, run=garbled)
        self.assertEqual(len(asked), 1)
        of("checkout", now=100 + goal_page.STATUS_EVERY, run=garbled)
        self.assertEqual(len(asked), 2)

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

    def test_a_thread_that_cannot_start_leaves_the_poll_answering_and_the_next_poll_trying(self):
        def no_thread(work):
            raise RuntimeError("can't start new thread")
        sheaf = Sheaf()
        self.assertEqual(goal_page.of("checkout", now=100, run=sheaf, start=no_thread),
                         {"url": None, "why": goal_page.ASKING})
        got = of("checkout", now=101, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/checkout.goal.md")

    def test_a_second_goal_asked_for_later_gets_its_page_at_once(self):
        (self.pm / "docs.goal.md").write_text("## Done when\n- [ ] one\n")
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        got = of("docs", now=101, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27419/claude/pm/docs.goal.md")

    def test_the_hub_is_asked_once_a_while(self):
        sheaf = Sheaf()
        for now in (100, 110, 120):
            of("checkout", now=now, run=sheaf)
        self.assertEqual(len(sheaf.asked), 1)
        of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(len(sheaf.asked), 2)

    def test_a_hub_that_comes_back_on_another_port_is_followed(self):
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        sheaf.port = 27500
        got = of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(got["url"], "http://127.0.0.1:27500/claude/pm/checkout.goal.md")

    def test_a_hub_gone_since_the_last_look_is_said(self):
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        sheaf.port = None
        got = of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(got, {"url": None, "why": goal_page.NO_HUB})

    def slow_sheaf(self):
        """A `sheaf` that answers after `goal_page.TIMEOUT`, run for real by `_run`."""
        slow = self.disk / "slow-sheaf"
        slow.write_text("#!/bin/sh\nsleep 5\n")
        slow.chmod(0o755)
        for name, value in (("SHEAF", str(slow)), ("TIMEOUT", 0.3)):
            self.addCleanup(setattr, goal_page, name, getattr(goal_page, name))
            setattr(goal_page, name, value)

    def test_a_sheaf_too_slow_to_answer_is_said_as_slow_and_not_as_no_hub(self):
        self.slow_sheaf()
        got = goal_page.of("checkout", now=100, start=inline)
        self.assertEqual(got, {"url": None, "why": goal_page.SLOW})

    def test_a_sheaf_too_slow_to_answer_keeps_the_hub_it_found_last_for_one_look(self):
        of("checkout", now=100, run=Sheaf())
        self.slow_sheaf()
        got = goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, start=inline)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})
        got = goal_page.of("checkout", now=100 + 2 * goal_page.STATUS_EVERY, start=inline)
        self.assertEqual(got, {"url": None, "why": goal_page.SLOW})

    def sheaf_says(self, code, err):
        """A `sheaf` that fails with `code`, nothing on stdout and `err` on stderr, run for
        real by `_run`."""
        said = self.disk / "sheaf-says"
        said.write_text(f"#!/bin/sh\nprintf '%s\\n' '{err}' >&2\nexit {code}\n")
        said.chmod(0o755)
        self.addCleanup(setattr, goal_page, "SHEAF", goal_page.SHEAF)
        goal_page.SHEAF = str(said)

    def test_a_hub_that_does_not_answer_sheaf_in_time_is_not_said_as_no_hub(self):
        # sheaf 1.0.3 `status` on a hub silent past sheaf's own 3 s (HubSilent): exit 1,
        # the line on stderr; "no hub is running" is printed only when none listens.
        of("checkout", now=100, run=Sheaf())
        self.sheaf_says(1, "  ! the sheaf hub on 127.0.0.1:27419 did not answer within 3 s; "
                           "try again, or run `sheaf restart`")
        got = goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, start=inline)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})
        got = goal_page.of("checkout", now=100 + 2 * goal_page.STATUS_EVERY, start=inline)
        self.assertEqual(got, {"url": None, "why": goal_page.UNSURE})

    def test_a_hub_that_hung_up_on_sheaf_is_silent_too(self):
        self.sheaf_says(1, "  ! the sheaf hub on 127.0.0.1:27419 proved itself and then ended the "
                           "connection, twice, and nothing was sent; try again, or run `sheaf restart`")
        self.assertEqual(goal_page.of("checkout", now=100, start=inline), {"url": None, "why": goal_page.UNSURE})

    def test_a_status_that_fails_otherwise_drops_the_link_and_is_not_said_as_no_hub(self):
        for err in ("  ! something else holds 127.0.0.1:27419, not your sheaf hub",
                    "sheaf: SHEAF_PORT is not a port: x", ""):
            with self.subTest(err=err):
                goal_page.forget()
                of("checkout", now=100, run=Sheaf())
                self.sheaf_says(1, err)
                got = goal_page.of("checkout", now=100 + goal_page.STATUS_EVERY, start=inline)
                self.assertEqual(got, {"url": None, "why": goal_page.FAILED})

    def test_a_status_that_says_neither_way_is_not_said_as_no_hub(self):
        self.assertEqual(of("checkout", now=100, run=lambda args: (0, "  all fine\n")),
                         {"url": None, "why": goal_page.FAILED})

    def test_a_root_sheaf_forgot_takes_the_link_away_at_the_next_look(self):
        sheaf = Sheaf()
        of("checkout", now=100, run=sheaf)
        self.registered()
        got = of("checkout", now=100 + goal_page.STATUS_EVERY, run=sheaf)
        self.assertEqual(got, {"url": None, "why": goal_page.NO_ROOT})


BOSS, OTHER = "7c1e4d5a-0000-4000-8000-00000000b055", "a9a9a529-0000-4000-8000-0000000000aa"


class Binding(Fixture):

    """A track's boss is the session a comment or Tell on its goal page reaches (boss-track/26). The
    page's session is only ever recorded by `sheaf open`; `docs.json` is read, never written."""
    def kept(self, **entries):
        (self.roots.with_name("docs.json")).write_text(json.dumps(entries))

    def bound_to(self, session):
        self.kept(**{"claude/pm/checkout.goal.md": {"target": {"agent": "claude-code", "session": session}}})

    def the_goal(self):
        return str(self.pm / "checkout.goal.md")

    def poll(self, sheaf, now=100, boss=BOSS):
        return goal_page.of("checkout", now=now, run=sheaf, start=inline, boss=boss)

    def test_a_page_nobody_rendered_is_bound_to_the_boss_under_the_config_folder_agentview_reads(self):
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened, [(["open", self.the_goal(), "--no-browser", "--agent", "claude-code",
                                          "--session", BOSS], {"CLAUDE_CONFIG_DIR": str(self.home)})])

    def test_a_page_bound_to_another_session_is_bound_to_the_boss_and_keeps_its_settings(self):
        self.kept(**{"claude/pm/checkout.goal.md": {
            "target": {"agent": "claude-code", "session": OTHER}, "title": "My goal", "toc": "never",
            "max_image_width": 900, "by": "Ana", "for": "", "theme": "plain", "credit": True}})
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened[0][0], [
            "open", self.the_goal(), "--no-browser", "--agent", "claude-code", "--session", BOSS,
            "--title=My goal", "--toc=never", "--max-image-width=900", "--by=Ana", "--for=",
            "--theme=plain", "--credit"])

    def test_settings_that_are_null_or_odd_are_not_passed_back(self):
        self.kept(**{"claude/pm/checkout.goal.md": {
            "target": None, "title": None, "toc": "sometimes", "max_image_width": True, "by": None,
            "for": None, "theme": None, "credit": False}})
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened[0][0][-2:], ["--session", BOSS])

    def test_a_page_already_bound_to_the_boss_is_left_alone(self):
        self.bound_to(BOSS)
        sheaf = Binder()
        self.poll(sheaf)
        self.poll(sheaf, now=100 + goal_page.STATUS_EVERY)
        self.assertEqual(sheaf.opened, [])

    def test_a_target_the_person_pointed_at_an_agent_token_is_left_alone(self):
        self.kept(**{"claude/pm/checkout.goal.md": {"target": {"kind": "agent", "token": "mine", "id": "x1"}}})
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened, [])

    def test_a_page_with_a_space_in_its_address_is_found_by_its_decoded_key(self):
        shutil.rmtree(self.home / ".git")
        notes = self.disk / "my notes"
        notes.mkdir()
        (self.pm / "checkout.goal.md").rename(notes / "checkout.goal.md")
        projects.pm_dir = lambda: notes
        self.registered(disk=(self.disk, False))
        self.kept(**{"disk/my notes/checkout.goal.md": {"target": {"agent": "claude-code", "session": BOSS}}})
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened, [])

    def test_no_docs_json_or_no_entry_for_the_page_is_nothing_to_keep_and_the_page_is_bound(self):
        for entries in (None, {}, {"claude/pm/checkout.goal.md": "x"}):
            with self.subTest(entries=entries):
                goal_page.forget()
                if entries is not None:
                    self.kept(**entries)
                sheaf = Binder()
                self.poll(sheaf)
                self.assertEqual(len(sheaf.opened), 1)

    def test_a_docs_json_that_cannot_be_read_binds_nothing_rather_than_wipe_settings_unseen(self):
        for text in ("", "not json", "[]"):
            with self.subTest(text=text):
                goal_page.forget()
                self.roots.with_name("docs.json").write_text(text)
                sheaf = Binder()
                self.poll(sheaf)
                self.assertEqual(sheaf.opened, [])

    def test_a_value_that_starts_with_a_dash_is_one_word_with_its_flag(self):
        self.kept(**{"claude/pm/checkout.goal.md": {"title": "-x", "by": "--help"}})
        sheaf = Binder()
        self.poll(sheaf)
        self.assertIn("--title=-x", sheaf.opened[0][0])
        self.assertIn("--by=--help", sheaf.opened[0][0])

    def test_a_goal_file_that_is_gone_is_not_bound(self):
        (self.pm / "checkout.goal.md").unlink()
        sheaf = Binder()
        goal_page._wanted.add(self.the_goal())          # a card asked before the file went
        goal_page._boss[self.the_goal()] = (BOSS, 100)
        goal_page._refresh(100, sheaf)
        self.assertEqual(sheaf.opened, [])

    def test_a_boss_no_card_has_named_for_a_while_is_not_bound_to_a_page(self):
        sheaf = Binder()
        self.poll(sheaf, now=100)
        self.bound_to(OTHER)
        goal_page._refresh(100 + goal_page.RETRY, sheaf)       # the track's column is gone: no card asked again
        self.assertEqual(len(sheaf.opened), 1)

    def test_a_bind_that_raises_takes_no_link_away(self):
        def raising(args, env=None):
            if args[:1] == ["open"]:
                raise ValueError("embedded null byte")
            return Sheaf()(args)
        got = self.poll(raising)
        self.assertEqual(got, {"url": "http://127.0.0.1:27419/claude/pm/checkout.goal.md", "why": ""})

    def test_with_no_boss_nothing_is_bound_and_a_boss_that_left_is_forgotten(self):
        sheaf = Binder()
        self.poll(sheaf, boss=None)
        self.assertEqual(sheaf.opened, [])
        self.poll(sheaf, now=200, boss=BOSS)
        self.poll(sheaf, now=200 + goal_page.RETRY, boss=None)
        self.poll(sheaf, now=200 + goal_page.RETRY + goal_page.STATUS_EVERY, boss=None)
        self.assertEqual(len(sheaf.opened), 1)

    def test_with_no_hub_or_no_root_no_open_runs(self):
        sheaf = Binder(port=None)
        self.poll(sheaf)
        self.assertEqual(sheaf.opened, [])
        goal_page.forget()
        self.registered()
        sheaf = Binder()
        self.poll(sheaf)
        self.assertEqual(sheaf.opened, [])

    def test_the_same_boss_is_bound_once_in_RETRY_seconds_worked_or_not_then_again(self):
        for code in (0, 1):
            with self.subTest(code=code):
                goal_page.forget()
                sheaf = Binder(code=code)
                for t in range(100, 100 + goal_page.RETRY, goal_page.STATUS_EVERY):
                    self.poll(sheaf, now=t)
                self.assertEqual(len(sheaf.opened), 1)
                self.poll(sheaf, now=100 + goal_page.RETRY)
                self.assertEqual(len(sheaf.opened), 2)

    def test_a_new_boss_session_binds_at_the_next_look_without_waiting(self):
        sheaf = Binder()
        self.poll(sheaf, now=100)
        self.poll(sheaf, now=100 + goal_page.STATUS_EVERY, boss="b055-new")
        self.assertEqual([a[0][-1] for a in sheaf.opened], [BOSS, "b055-new"])

    def test_a_render_from_another_session_is_bound_back_once_RETRY_has_passed(self):
        sheaf = Binder()
        self.poll(sheaf, now=100)
        self.bound_to(OTHER)
        self.poll(sheaf, now=100 + goal_page.RETRY)
        self.assertEqual(len(sheaf.opened), 2)

    def test_the_poll_does_not_wait_for_the_bind(self):
        started = []
        self.addCleanup(goal_page._busy.__setitem__, 0, False)      # the refresh asked for never ran
        sheaf = Binder()
        goal_page.of("checkout", now=100, run=sheaf, start=started.append, boss=BOSS)
        self.assertEqual((sheaf.asked, sheaf.opened), ([], []))
        self.assertEqual(len(started), 1)


class Scope(unittest.TestCase):
    """`sheaf open` can start a hub; one started from agentview's service would die with its restart."""
    def argv_of(self, args, missing=False):
        seen = []

        def fake(argv, **kw):
            seen.append((argv, kw))
            if missing and argv[0] == "systemd-run":
                raise FileNotFoundError(argv[0])
            return subprocess.CompletedProcess(argv, 0, "", "")
        real, subprocess_run = goal_page.subprocess.run, fake
        goal_page.subprocess.run = subprocess_run
        self.addCleanup(setattr, goal_page.subprocess, "run", real)
        return goal_page._run(args, env={"CLAUDE_CONFIG_DIR": "/x"}), seen

    def test_an_open_runs_in_a_scope_of_its_own_with_the_environment_it_was_given(self):
        (code, _), seen = self.argv_of(["open", "g.md", "--no-browser"])
        self.assertEqual(seen[0][0], [*goal_page.SCOPE, "sheaf", "open", "g.md", "--no-browser"])
        self.assertEqual(goal_page.SCOPE[:3], ["systemd-run", "--user", "--scope"])
        self.assertEqual(seen[0][1]["env"]["CLAUDE_CONFIG_DIR"], "/x")

    def test_status_is_not_scoped(self):
        _, seen = self.argv_of(["status"])
        self.assertEqual(seen[0][0], ["sheaf", "status"])

    def test_without_systemd_run_the_open_does_not_run_at_all(self):
        (code, _), seen = self.argv_of(["open", "g.md"], missing=True)
        self.assertEqual(code, goal_page.MISSING)
        self.assertEqual([a[0][0] for a in seen], ["systemd-run"])


if __name__ == "__main__":
    unittest.main()
