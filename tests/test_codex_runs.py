"""A `codex exec` run on the overview, through `roster()` with fake providers.

A short run does not get a tile: it is movement inside the tile of the session
that started it ("waiting on: codex review, 2 min"), found by the processes
above the run. A run nobody started from a session on the page gets a tile of
its own, marked exec. R15: its writes are counted once, in one of the two.
Names and texts are invented.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_columns import Base, session
from test_providers import Fake

NOW = time.time()


def ago(minutes):
    return int((time.time() - minutes * 60) * 1000)


class Claude(Fake):
    name = "claude"


class Codex(Fake):
    name = "codex"
    capabilities = {"jump", "branch"}


def starter(sid="s", pid=100, **over):
    """A Claude session, idle, doing nothing of its own."""
    return session(sid, status="idle", pid=pid, updatedAt=ago(30), quietFor=29.0, **over)


def run(sid="r", pid=4242, above=(200, 100), minutes=2.0, label="codex review", project="maple", kind="exec", **over):
    """A `codex exec` run that began `minutes` ago, with these processes above it."""
    return session(sid, project, status="busy", pid=pid, kind=kind, run=label,
                   ancestors=list(above) if isinstance(above, (tuple, list)) else above,
                   startedAt=ago(minutes), updatedAt=ago(minutes), quietFor=0.05, **over)


class Folded(Base):
    def both(self, claude=(), codex=()):
        self.config = self.config or {}
        import json
        fleet.CONFIG.write_text(json.dumps(self.config))
        return fleet.roster(providers=[Claude(claude), Codex(codex)])

    def tiles(self, *a, **kw):
        return {t["key"]: t for c in self.both(*a, **kw)["columns"] for t in c["sessions"]}

    def test_a_run_started_by_a_session_is_in_that_session_s_tile_and_has_none_of_its_own(self):
        got = self.tiles([starter()], [run()])
        self.assertEqual(list(got), ["claude:s"])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: codex review, 2 min")
        self.assertTrue(got["claude:s"]["moving"])

    def test_the_session_is_moving_not_idle_while_its_run_is_alive(self):
        got = self.both([starter()], [run()])
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 0, "moving": 1})
        self.assertEqual(got["columns"][0]["summary"], {"moving": 1, "stuck": 0, "idle": 0})
        self.assertEqual(got["columns"][0]["state"], "moving")

    def test_without_the_run_the_same_session_is_idle(self):
        got = self.both([starter()], [])
        self.assertEqual(got["counts"]["moving"], 0)
        self.assertEqual(got["columns"][0]["state"], "idle")

    def test_a_plain_exec_run_is_named_for_what_it_is(self):
        got = self.tiles([starter()], [run(label="codex exec")])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: codex exec, 2 min")

    def test_a_session_that_is_writing_says_so_and_is_moving_either_way(self):
        got = self.tiles([session("s", status="busy", pid=100, quietFor=0.1)], [run()])
        self.assertEqual(got["claude:s"]["movement"]["kind"], "writing")
        self.assertTrue(got["claude:s"]["moving"])

    def test_the_nearest_session_above_the_run_is_its_starter(self):
        outer, inner = starter("outer", pid=100), starter("inner", pid=150)
        got = self.tiles([outer, inner], [run(above=(200, 150, 100))])
        self.assertEqual(got["claude:inner"]["movement"]["text"], "waiting on: codex review, 2 min")
        self.assertEqual(got["claude:outer"]["movement"]["kind"], "idle")

    def test_a_run_in_another_project_is_still_its_starter_s_movement(self):
        got = self.both([starter()], [run(project="orchard")])
        self.assertEqual([c["name"] for c in got["columns"]], ["Maple"])

    def test_two_runs_under_one_session_are_two_jobs(self):
        got = self.tiles([starter()], [run("r1", 4242, minutes=2.0), run("r2", 4300, minutes=5.0)])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: 2 background jobs, 5 min")

    def test_a_run_that_is_a_background_task_of_the_session_is_that_job_and_not_a_second_one(self):
        # Claude lists the shell it started, and the run is what that shell runs.
        job = {"id": "bg1", "label": "Second opinion on the diff", "since": 2.0}
        got = self.tiles([starter(bgTasks=[job])], [run(task="bg1")])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: Second opinion on the diff, 2 min")

    def test_a_run_under_some_other_task_is_one_more_job(self):
        job = {"id": "bg1", "label": "A dev server", "since": 40.0}
        got = self.tiles([starter(bgTasks=[job])], [run(task="bg9")])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: 2 background jobs, 40 min")

    def test_a_task_that_cannot_be_matched_does_not_hide_the_run(self):
        listed = {"label": "Second opinion", "since": 2.0}                   # no id to match
        for task in (None, "", "   ", 5, True, ["bg1"], {"id": "bg1"}):
            for job in (listed, {**listed, "id": 7}, {**listed, "id": ""}):
                with self.subTest(task=task, job=job):
                    got = self.tiles([starter(bgTasks=[job])], [run(task=task)])
                    self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: 2 background jobs, 2 min")

    def test_a_run_matched_to_a_task_is_still_the_session_moving_by_its_writes(self):
        job = {"id": "bg1", "label": "Second opinion", "since": 30.0}
        got = self.tiles([starter(bgTasks=[job])], [run(task="bg1", writes=[2] * 30)])
        self.assertTrue(got["claude:s"]["moving"])

    def test_a_run_s_two_threads_are_one_run(self):
        # `codex exec review` writes a rollout for the run and one for its review.
        got = self.tiles([starter()], [run("a", 4242, label="codex exec"), run("b", 4242, label="codex review")])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: codex review, 2 min")

    def test_a_run_is_as_old_as_its_oldest_thread(self):
        got = self.tiles([starter()], [run("a", 4242, minutes=2.0), run("b", 4242, minutes=5.0)])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: codex review, 5 min")

    def test_a_session_nothing_can_be_made_of_is_nobody_s_starter(self):
        nameless = {k: v for k, v in starter().items() if k != "id"}
        _, tiles = Alone.run_tile(self, run(), claude=[nameless])
        self.assertEqual(list(tiles), ["codex:r"])

    def test_a_run_inside_a_run_is_in_the_session_above_both(self):
        got = self.tiles([starter()], [run("outer", 4242, above=(200, 100)),
                                       run("inner", 4300, above=(4242, 200, 100), label="codex exec")])
        self.assertEqual(list(got), ["claude:s"])
        self.assertEqual(got["claude:s"]["movement"]["text"], "waiting on: 2 background jobs, 2 min")

    def test_a_session_of_any_provider_may_be_the_starter(self):
        class Other(Fake):
            name = "other"
        out = fleet.roster(providers=[Other([starter()]), Codex([run()])])
        self.assertEqual([t["key"] for c in out["columns"] for t in c["sessions"]], ["other:s"])


class Alone(Base):
    def run_tile(self, *codex, claude=()):
        import json
        fleet.CONFIG.write_text(json.dumps(self.config))
        got = fleet.roster(providers=[Claude(claude), Codex(codex)])
        return got, {t["key"]: t for c in got["columns"] for t in c["sessions"]}

    def test_a_run_with_no_session_above_it_is_a_tile_marked_exec_in_its_launch_folder(self):
        got, tiles = self.run_tile(run(above=(200, 1234)), claude=[starter(pid=555)])
        self.assertEqual(sorted(tiles), ["claude:s", "codex:r"])
        self.assertEqual(tiles["codex:r"]["tags"], ["codex", "exec"])
        self.assertEqual([c["name"] for c in got["columns"]], ["Maple"])

    def test_a_run_whose_processes_could_not_be_walked_is_a_tile_marked_exec(self):
        _, tiles = self.run_tile(run(above=()), claude=[starter()])
        self.assertEqual(tiles["codex:r"]["tags"], ["codex", "exec"])
        self.assertEqual(tiles["claude:s"]["movement"]["kind"], "idle")

    def test_a_run_with_no_process_known_is_a_tile_marked_exec(self):
        raw = run(above=())
        del raw["pid"]
        _, tiles = self.run_tile(raw, claude=[starter()])
        self.assertIn("codex:r", tiles)

    def test_a_routine_is_not_a_starter_because_it_has_no_tile(self):
        _, tiles = self.run_tile(run(), claude=[starter(routine="nightly-report")])
        self.assertEqual(list(tiles), ["codex:r"])

    def test_a_run_s_tile_says_it_is_moving_while_it_writes(self):
        _, tiles = self.run_tile(run(above=()))
        self.assertTrue(tiles["codex:r"]["moving"])

    def test_two_threads_of_one_orphan_run_are_one_tile_that_is_a_review(self):
        _, tiles = self.run_tile(run("a", 4242, above=(), label="codex exec"),
                                 run("b", 4242, above=(), label="codex review"))
        self.assertEqual(list(tiles), ["codex:a"])

    def test_the_oldest_thread_stands_for_a_run_that_has_none_to_show(self):
        _, tiles = self.run_tile(run("review", 4242, above=(), minutes=1.0, label="codex review"),
                                 run("main", 4242, above=(), minutes=3.0, label="codex exec"))
        self.assertEqual(list(tiles), ["codex:main"])

    def test_the_newest_thread_says_what_the_run_is_doing_whatever_the_provider_calls_it(self):
        for older, newer in (("codex exec", "codex review"), ("alpha", "beta"), ("beta", "alpha")):
            for order in (1, -1):
                with self.subTest(older=older, newer=newer, order=order):
                    threads = [run("a", 4242, minutes=4.0, label=older), run("b", 4242, minutes=1.0, label=newer)]
                    _, tiles = self.run_tile(*threads[::order], claude=[starter()])
                    self.assertEqual(tiles["claude:s"]["movement"]["text"], f"waiting on: {newer}, 4 min")

    def test_threads_that_do_not_say_when_they_began_are_taken_in_the_order_given(self):
        a, b = run("a", 4242, label="first"), run("b", 4242, label="second")
        a["startedAt"] = b["startedAt"] = 0
        _, tiles = self.run_tile(a, b, claude=[starter()])
        self.assertTrue(tiles["claude:s"]["movement"]["text"].startswith("waiting on: second,"))

    def test_a_tile_is_marked_exec_because_it_is_a_run_not_because_of_what_the_provider_calls_its_kind(self):
        odd = run("o", 4242, above=(), kind="batch", label="a one-shot")
        plain = session("p", status="busy", pid=4300, kind="exec")
        _, tiles = self.run_tile(odd, plain)
        self.assertEqual(tiles["codex:o"]["tags"], ["codex", "exec"])
        self.assertEqual(tiles["codex:p"]["tags"], ["codex"])

    def test_a_row_whose_run_is_not_a_name_is_not_a_run(self):
        for odd in ("", "   ", "\n", 5, 1.5, True, None, ["codex exec"], {"run": "x"}):
            with self.subTest(odd=odd):
                _, tiles = self.run_tile(session("x", status="busy", pid=4242, ancestors=[200, 100], run=odd),
                                         claude=[starter()])
                self.assertEqual(tiles["codex:x"]["tags"], ["codex"])
                self.assertNotIn("waiting on", tiles["claude:s"]["movement"]["text"])

    def test_an_interactive_codex_session_is_a_tile_that_is_not_exec(self):
        _, tiles = self.run_tile(session("i", status="idle", pid=4242, ancestors=[100]), claude=[starter()])
        self.assertEqual(tiles["codex:i"]["tags"], ["codex"])

    def test_a_pid_that_is_not_a_number_is_nobody_s(self):
        for odd in ([1], {"a": 1}, "100", None, 1.5, True, -3):
            with self.subTest(odd=odd):
                _, tiles = self.run_tile(run(pid=odd, above=(100,)), claude=[starter(pid=odd)])
                self.assertEqual(sorted(tiles), ["claude:s", "codex:r"])

    def test_what_a_provider_says_about_ancestors_is_checked(self):
        for odd in (None, "100", 100, [True], ["100"], [None, 1.5], {"a": 1}, [-4, 0], [[100]], [{"a": 100}]):
            with self.subTest(odd=odd):
                _, tiles = self.run_tile(run(above=odd), claude=[starter()])
                self.assertIn("codex:r", tiles)


class Counted(Base):
    """R15: the run's writes are in one place, never two."""

    def column(self, claude, codex):
        import json
        fleet.CONFIG.write_text(json.dumps(self.config))
        return fleet.roster(providers=[Claude(claude), Codex(codex)])["columns"][0]

    def test_a_folded_run_adds_its_writes_to_its_starter_once(self):
        got = self.column([starter(writes=[1] * 30)], [run(writes=[2] * 30)])
        self.assertEqual(got["strip"], [3] * 30)

    def test_the_run_s_writes_are_not_added_again_by_a_tile_of_its_own(self):
        got = self.column([starter(writes=[1] * 30)], [run(writes=[2] * 30)])
        self.assertEqual([t["key"] for t in got["sessions"]], ["claude:s"])
        self.assertEqual(sum(got["strip"]), 90)

    def test_a_run_that_is_one_of_the_session_s_tasks_still_adds_its_writes_once(self):
        job = {"id": "bg1", "label": "Second opinion", "since": 2.0}
        got = self.column([starter(bgTasks=[job], writes=[1] * 30)],
                          [run(task="bg1", writes=[2] * 30)])
        self.assertEqual(got["strip"], [3] * 30)

    def test_two_threads_of_one_run_add_both_their_rollouts(self):
        got = self.column([starter(writes=[1] * 30)],
                          [run("a", 4242, writes=[2] * 30), run("b", 4242, writes=[5] * 30)])
        self.assertEqual(got["strip"], [8] * 30)

    def test_an_orphan_run_counts_its_writes_in_its_own_column_once(self):
        got = self.column([], [run(above=(), writes=[2] * 30)])
        self.assertEqual(got["strip"], [2] * 30)

    def test_a_minute_nobody_could_see_stays_unknown(self):
        unseen = [None] + [2] * 29
        got = self.column([starter(writes=[1] * 30)], [run(writes=unseen)])
        self.assertEqual(got["strip"], [None] + [3] * 29)

    def test_a_starter_whose_provider_counts_nothing_is_left_out_not_counted_as_quiet(self):
        got = self.column([starter()], [run(writes=[2] * 30)])
        self.assertEqual(got["strip"], [None] * 30)

    def test_a_run_that_counts_nothing_changes_nothing(self):
        got = self.column([starter(writes=[1] * 30)], [run()])
        self.assertEqual(got["strip"], [1] * 30)


if __name__ == "__main__":
    unittest.main()
