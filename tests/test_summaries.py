"""Two lines under each search result: what a conversation was about, and
where it ended. The model call is the seam: every test here hands `summarize`
a stand-in for it and looks at what came out the other side. The transcripts
are made up (test_archive.py's kettle), never real ones.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import archive
from providers import claude
from test_archive import KETTLE, OTHER, SID, Home, said, typed

LATER = time.time() + 3600        # an hour on: every transcript here has been quiet for it


class Model:
    """Stands in for `claude -p --model haiku`. Records what it was shown."""

    def __init__(self, *answers):
        self.answers = list(answers) or ["The kettle whistling.\nDone: the whistle was explained."]
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers[min(len(self.prompts), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer, 0.004


class Summarised(Home):
    def summarize(self, ask=None, **kw):
        kw.setdefault("now", LATER)
        return archive.summarize(path=self.db, ask=ask or Model(), **kw)

    def summary(self, sid=SID):
        rows = self.rows("SELECT about, ended FROM summaries WHERE id=? AND about<>''", sid)
        return rows[0] if rows else None


class Making(Summarised, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write(SID, KETTLE)
        self.update()

    def test_a_result_shows_what_it_was_about_and_where_it_ended(self):
        self.summarize()
        hit = archive.search("kettle", path=self.db)[0]
        self.assertEqual(hit["summary"], {"about": "The kettle whistling.",
                                          "ended": "Done: the whistle was explained.",
                                          "stale": False})

    def test_a_conversation_without_a_summary_shows_only_its_title(self):
        hit = archive.search("kettle", path=self.db)[0]
        self.assertIsNone(hit["summary"])
        self.assertEqual(hit["title"], "Kettle physics")

    def test_the_model_is_shown_how_it_began_and_how_it_ended(self):
        model = Model()
        self.summarize(model)
        shown = model.prompts[0]
        self.assertIn("Kettle physics", shown)                        # the title
        self.assertIn("Why does the kettle whistle?", shown)          # the first thing asked
        self.assertIn("Copper conducts heat well.", shown)            # the last thing said
        for machine in ("REMINDERTEXT", "TOOLRESULTTEXT", "THINKINGTEXT", "HOOKTEXT"):
            self.assertNotIn(machine, shown)

    def test_what_the_model_sees_is_bounded_however_long_the_conversation(self):
        records = []
        for i in range(300):
            records += [typed(2 * i, f"question {i} " + "padding " * 400),
                        said(2 * i + 1, f"answer {i} " + "padding " * 4000)]
        self.write(OTHER, [dict(r, sessionId=OTHER) for r in records])
        self.update()
        model = Model()
        self.summarize(model)
        self.assertTrue(all(len(p) < 12000 for p in model.prompts), [len(p) for p in model.prompts])
        long_one = next(p for p in model.prompts if "question 299" in p)
        self.assertIn("question 0 ", long_one)                        # how it began
        self.assertNotIn("question 150 ", long_one)                   # not the middle
        self.assertNotIn("answer 0 ", long_one)

    def test_two_lines_come_back_two_lines_are_kept(self):
        self.summarize(Model("About: Why a kettle whistles.\nEnded: finished, nothing pending.\n"))
        self.assertEqual(self.summary(), ("Why a kettle whistles.", "finished, nothing pending."))

    def test_an_answer_that_is_not_two_lines_is_a_failure_not_a_summary(self):
        run = self.summarize(Model("just one line"))
        self.assertEqual((run["made"], run["failed"]), (0, 1))
        self.assertIsNone(self.summary())

    def test_numbering_and_labels_the_model_adds_are_dropped(self):
        for answer in ("1. Why a kettle whistles.\n2. Finished.", "1) Why a kettle whistles.\n2) Finished.",
                       "- About: Why a kettle whistles.\n- Ended - Finished.", "\n\nWhy a kettle whistles.\n\nFinished.\n"):
            self.assertEqual(archive.two_lines(answer), ("Why a kettle whistles.", "Finished."), answer)
        # ...but a number that belongs to the sentence stays.
        self.assertEqual(archive.two_lines("3.5 GB of logs cleared.\nDone."), ("3.5 GB of logs cleared.", "Done."))
        self.assertEqual(archive.two_lines("2026 taxes, F24 forms.\nWaiting."), ("2026 taxes, F24 forms.", "Waiting."))

    def test_a_long_line_is_cut(self):
        self.summarize(Model("a" * 500 + "\n" + "b" * 500))
        about, ended = self.summary()
        self.assertLessEqual(len(about), archive.LINE)
        self.assertLessEqual(len(ended), archive.LINE)


class Choosing(Summarised, unittest.TestCase):
    """Which conversations get a summary, and when again."""

    def setUp(self):
        super().setUp()
        self.path = self.write(SID, KETTLE)
        self.update()

    def grow(self, *records):
        self.write(SID, list(records), mode="a")
        self.update()

    def test_a_conversation_still_being_written_waits_until_it_has_been_quiet(self):
        model = Model()
        run = self.summarize(model, now=time.time() + 60)
        self.assertEqual((run["asked"], model.prompts), (0, []))
        self.assertEqual(run["waiting"], 0)
        self.summarize(model, now=time.time() + archive.QUIET + 60)
        self.assertEqual(len(model.prompts), 1)

    def test_quiet_is_judged_on_the_transcript_not_on_the_index(self):
        # The index last read it an hour ago; someone has written to it since.
        # The update timer has not come round yet, so the index still says quiet.
        model = Model()
        self.write(SID, [typed(30, "and lead?"), said(31, "Lead is soft.")], mode="a")
        run = self.summarize(model)
        self.assertEqual((run["asked"], model.prompts), (0, []))
        self.update()                                     # the index catches up...
        self.summarize(model)                             # ...and only then is it summarised
        self.assertIn("Lead is soft.", model.prompts[0])

    def test_a_transcript_touched_since_the_last_read_waits_too(self):
        model = Model()
        later = time.time() + 5
        os.utime(self.path, (later, later))
        self.assertEqual(self.summarize(model)["asked"], 0)
        self.update()
        self.assertEqual(self.summarize(model)["asked"], 1)

    def test_a_summary_stands_until_the_conversation_changes(self):
        model = Model()
        self.summarize(model)
        self.summarize(model)
        self.assertEqual(len(model.prompts), 1)

    def test_a_conversation_that_grew_is_summarised_again(self):
        model = Model("First.\nDone.", "Second.\nWaiting on you.")
        self.summarize(model)
        self.grow(typed(30, "and lead?"), said(31, "Lead is soft and heavy."))
        self.summarize(model)
        self.assertEqual(len(model.prompts), 2)
        self.assertIn("Lead is soft and heavy.", model.prompts[1])
        self.assertEqual(self.summary(), ("Second.", "Waiting on you."))

    def test_a_change_the_model_cannot_see_does_not_cost_a_call(self):
        # Tool output makes the transcript longer; none of it is in the index.
        model = Model()
        self.summarize(model)
        self.grow(said(30, {"type": "tool_use", "id": "t9", "name": "Bash", "input": {"command": "ls"}}))
        run = self.summarize(model)
        self.assertEqual((len(model.prompts), run["asked"]), (1, 0))

    def test_a_summary_of_a_conversation_that_moved_on_is_flagged_earlier(self):
        self.summarize()
        self.grow(typed(30, "and lead?"), said(31, "Lead is soft."))
        self.assertTrue(archive.search("kettle", path=self.db)[0]["summary"]["stale"])
        self.summarize()
        self.assertFalse(archive.search("kettle", path=self.db)[0]["summary"]["stale"])

    def test_the_most_recently_active_conversation_goes_first(self):
        # KETTLE was last active on 2026-08-10; this one a month later.
        self.write(OTHER, [typed(1, "tidy the garden", sid=OTHER) | {"timestamp": "2026-09-01T09:00:00.000Z"},
                           said(2, "Done.", sid=OTHER) | {"timestamp": "2026-09-01T09:01:00.000Z"}])
        self.update()
        model = Model()
        self.summarize(model, limit=1)
        self.assertIn("tidy the garden", model.prompts[0])
        self.summarize(model, limit=1)
        self.assertIn("Why does the kettle whistle?", model.prompts[1])

    def test_a_conversation_with_nothing_said_has_nothing_to_summarise(self):
        empty = "00000000-0000-4000-8000-0000000000ee"
        self.write(empty, [{"type": "mode", "mode": "normal", "sessionId": empty, "entrypoint": "cli"}])
        self.update()
        model = Model()
        self.summarize(model)
        self.assertEqual(len(model.prompts), 1)


class Pacing(Summarised, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ids = []
        for n in range(7):
            sid = f"00000000-0000-4000-8000-0000000001{n:02d}"
            self.ids.append(sid)
            self.write(sid, [typed(1, f"topic number {n}", sid=sid), said(2, f"Answer {n}.", sid=sid)])
        self.update()

    def test_a_run_makes_at_most_the_number_it_is_allowed(self):
        run = self.summarize(limit=3)
        self.assertEqual((run["made"], run["waiting"]), (3, 4))
        run = self.summarize(limit=3)
        self.assertEqual((run["made"], run["waiting"]), (3, 1))
        run = self.summarize(limit=3)
        self.assertEqual((run["made"], run["waiting"]), (1, 0))

    def test_a_run_with_no_limit_given_uses_the_written_down_pace(self):
        run = self.summarize()
        self.assertEqual(run["made"], min(7, archive.PER_RUN))

    def test_three_failures_in_a_row_end_the_run(self):
        # The plan's quota is spent, or nobody is logged in: stop asking.
        model = Model(archive.Failed("out of quota"))
        run = self.summarize(model)
        self.assertEqual((run["made"], run["failed"], len(model.prompts)), (0, 3, 3))
        self.assertIn("out of quota", run["error"])

    def test_one_failure_is_tried_again_next_run(self):
        model = Model(archive.Failed("boom"), "About.\nDone.")
        run = self.summarize(model, limit=1)
        self.assertEqual((run["made"], run["failed"]), (0, 1))
        run = self.summarize(model, limit=7)
        self.assertEqual(run["made"], 7)              # the one that failed is among them


class BeforeTheFirstRun(Summarised, unittest.TestCase):
    """The index a search reads may have been built before summaries existed:
    the page must go on working until the next `update` adds the table."""

    def test_an_index_from_before_summaries_still_answers(self):
        self.write(SID, KETTLE)
        self.update()
        con = sqlite3.connect(self.db)
        con.execute("DROP TABLE summaries")
        con.commit()
        con.close()
        hit = archive.search("kettle", path=self.db)[0]
        self.assertEqual((hit["id"], hit["summary"], hit["title"]), (SID, None, "Kettle physics"))
        self.assertEqual(archive.stats(self.db)["summaries"], 0)
        self.update()                                    # the next run adds the table again
        self.assertEqual(self.rows("SELECT COUNT(*) FROM summaries"), [(0,)])


class Overlapping(Summarised, unittest.TestCase):
    """The update job and the summary job are separate timers. One can finish
    while the other is waiting for the model."""

    def test_a_transcript_deleted_during_the_call_leaves_no_summary_behind(self):
        path = self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "unrelated", sid=OTHER)])
        self.update()
        outer = self

        class Deleting(Model):
            def __call__(self, prompt):
                if "kettle" in prompt:
                    path.unlink()
                    outer.update()                       # the update job runs in the meantime
                return super().__call__(prompt)

        self.summarize(Deleting())
        self.assertEqual(self.rows("SELECT id FROM summaries WHERE id=?", SID), [])
        self.assertEqual(self.rows("SELECT id FROM conversations WHERE id=?", SID), [])

    def test_the_same_for_a_summary_that_failed(self):
        path = self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "unrelated", sid=OTHER)])
        self.update()
        outer = self

        def failing(prompt):
            path.unlink()
            outer.update()
            raise archive.Failed("boom")

        self.summarize(failing, limit=1)
        self.assertEqual(self.rows("SELECT id FROM summaries WHERE id=?", SID), [])


class GivingUp(Summarised, unittest.TestCase):
    def test_a_conversation_that_keeps_failing_is_left_alone_until_it_changes(self):
        self.write(SID, KETTLE)
        self.update()
        stubborn = Model(archive.Failed("boom"))
        for _ in range(archive.TRIES + 3):
            self.summarize(stubborn, limit=1)
        self.assertEqual(len(stubborn.prompts), archive.TRIES)
        self.write(SID, [typed(30, "and lead?"), said(31, "Lead is soft.")], mode="a")
        self.update()
        self.summarize(stubborn, limit=1)
        self.assertEqual(len(stubborn.prompts), archive.TRIES + 1)


class Surviving(Summarised, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.path = self.write(SID, KETTLE)
        self.update()
        self.summarize()

    def test_a_summary_outlives_a_rebuild_of_the_index(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE meta SET value='0' WHERE key='schema'")
        con.commit()
        con.close()
        self.update()                                    # schema unknown: derived data is rebuilt
        self.assertEqual(self.summary()[0], "The kettle whistling.")
        model = Model()
        self.summarize(model)
        self.assertEqual(model.prompts, [])              # and it is not paid for twice

    def test_a_summary_goes_with_its_transcript(self):
        self.path.unlink()
        self.write(OTHER, [typed(1, "unrelated", sid=OTHER)])
        self.update()
        self.assertIsNone(self.summary())

    def test_a_summary_survives_the_transcript_being_read_from_scratch(self):
        self.write(SID, KETTLE)                          # rewritten, same words
        os.utime(self.path, (time.time() + 5, time.time() + 5))
        self.update()
        self.assertIsNotNone(self.summary())


class Asking(unittest.TestCase):
    """The one place that runs `claude`."""

    def run_ask(self, stdout=None, **env):
        stdout = stdout if stdout is not None else json.dumps(
            {"result": "About it.\nDone.", "total_cost_usd": 0.004, "is_error": False})
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        home = Path(tempfile.mkdtemp())
        with mock.patch.object(archive.subprocess, "run", return_value=done) as run, \
                mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home), "TMUX": "x", "TMUX_PANE": "%1",
                                              "CLAUDE_CODE_CHILD_SESSION": "1",
                                              "CLAUDE_CODE_MESSAGING_SOCKET": "/x", **env}):
            got = archive.ask_model("the excerpt")
        return got, run.call_args, home

    def test_it_is_the_cli_on_haiku_with_hooks_and_tools_off(self):
        got, call, _ = self.run_ask()
        self.assertEqual(got, ("About it.\nDone.", 0.004))
        argv = call.args[0]
        self.assertEqual(argv[1:2], ["-p"])
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertIn("--safe-mode", argv)                            # no hooks, plugins or CLAUDE.md
        self.assertEqual(argv[argv.index("--tools") + 1], "")         # nothing it could run

    def test_it_is_the_plan_that_pays_never_an_api_key(self):
        _, call, _ = self.run_ask(ANTHROPIC_API_KEY="sk-not-real", ANTHROPIC_AUTH_TOKEN="x")
        self.assertNotIn("ANTHROPIC_API_KEY", call.kwargs["env"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", call.kwargs["env"])

    def test_the_conversation_goes_in_on_stdin_never_on_the_command_line(self):
        _, call, _ = self.run_ask()
        self.assertEqual(call.kwargs["input"], "the excerpt")
        self.assertNotIn("the excerpt", call.args[0])

    def test_it_runs_where_the_page_knows_to_ignore_it_and_not_under_the_callers_session(self):
        _, call, home = self.run_ask()
        self.assertEqual(Path(call.kwargs["cwd"]), claude.helper_dir(home))
        self.assertTrue(claude.helper_dir(home).is_dir())
        env = call.kwargs["env"]
        for name in ("TMUX", "TMUX_PANE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET"):
            self.assertNotIn(name, env)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(home))

    def test_it_does_not_think(self):
        # Two lines of answer cost 2,000 thinking tokens and half a minute otherwise.
        _, call, _ = self.run_ask()
        self.assertEqual(call.kwargs["env"]["MAX_THINKING_TOKENS"], "0")

    def test_it_cannot_run_away(self):
        _, call, _ = self.run_ask()
        self.assertGreater(call.kwargs["timeout"], 0)
        self.assertIn("--max-budget-usd", call.args[0])

    def test_a_failed_run_says_why_and_never_quotes_the_conversation(self):
        for stdout in ('{"is_error": true, "result": "Credit balance is too low"}', "not json", ""):
            with self.assertRaises(archive.Failed) as ctx:
                self.run_ask(stdout)
            self.assertNotIn("the excerpt", str(ctx.exception))
        with self.assertRaisesRegex(archive.Failed, "Credit balance"):
            self.run_ask('{"is_error": true, "result": "Credit balance is too low"}')

    def test_what_claude_says_about_a_failure_is_scrubbed_of_what_it_was_sent(self):
        secret = "the quarterly figures for the Marlowe account were altered by hand"
        prompt = f"Instructions here, and then the conversation.\n{secret}\nAnd more text after it."
        for stdout, stderr in (
                (json.dumps({"is_error": True, "result": f"Invalid input near: {secret[:45]}"}), ""),
                ("", f"error: could not parse the text '{secret[10:60]}' at line 2"),
                ("not json", f"{secret}")):
            done = subprocess.CompletedProcess([], 1, stdout=stdout, stderr=stderr)
            with mock.patch.object(archive.subprocess, "run", return_value=done), \
                    mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tempfile.mkdtemp()}):
                with self.assertRaises(archive.Failed) as ctx:
                    archive.ask_model(prompt)
            message = str(ctx.exception)
            for at in range(len(secret) - 19):
                self.assertNotIn(secret[at:at + 20], message, message)
            self.assertTrue(message)                               # it still says something

    def test_a_message_that_quotes_nothing_is_left_alone(self):
        done = subprocess.CompletedProcess([], 1, stdout=json.dumps(
            {"is_error": True, "result": "Credit balance is too low"}), stderr="")
        with mock.patch.object(archive.subprocess, "run", return_value=done), \
                mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tempfile.mkdtemp()}):
            with self.assertRaisesRegex(archive.Failed, "Credit balance is too low"):
                archive.ask_model("some excerpt of a conversation about kettles")

    def test_a_timeout_and_a_missing_binary_are_failures_too(self):
        for exc in (subprocess.TimeoutExpired("claude", 1), FileNotFoundError("claude")):
            with mock.patch.object(archive.subprocess, "run", side_effect=exc), \
                    mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tempfile.mkdtemp()}):
                with self.assertRaises(archive.Failed):
                    archive.ask_model("x")


class Endpoint(Summarised, unittest.TestCase):
    """The route the page calls, over HTTP: the row carries the two lines."""

    def setUp(self):
        super().setUp()
        self.env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.root)
        self.write(SID, KETTLE)
        self.update()
        import server
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.env
        super().tearDown()

    def get(self, query):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.httpd.server_port}/api/search?q={query}",
                                    timeout=10) as r:
            return json.load(r)

    def test_a_row_carries_its_two_lines_once_it_has_them(self):
        self.assertIsNone(self.get("kettle")["results"][0]["summary"])
        self.summarize()
        row = self.get("kettle")["results"][0]
        self.assertEqual(row["summary"]["about"], "The kettle whistling.")
        self.assertEqual(row["summary"]["ended"], "Done: the whistle was explained.")
        self.assertEqual(self.get("kettle")["index"]["summaries"], 1)


class OffThePage(unittest.TestCase):
    """A summary run is a session for the few seconds it lasts. The page and
    the log must not see it."""

    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.cfg, self.proc = base / "claude", base / "proc"
        (self.cfg / "sessions").mkdir(parents=True)
        self.proc.mkdir()

    def peer(self, pid, sid, cwd, entrypoint):
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "stat").write_text(
            f"{pid} (claude) S 1 {pid} {pid} 34870 -1 4194304 1 0 0 0 1 2 0 0 20 0 15 0 1640779 0 0\n")
        rec = {"pid": pid, "sessionId": sid, "kind": "interactive", "entrypoint": entrypoint,
               "status": "busy", "procStart": "1640779", "cwd": str(cwd), "name": sid}
        (self.cfg / "sessions" / f"{pid}.json").write_text(json.dumps(rec))

    def listed(self):
        return sorted(s["id"] for s in claude.ClaudeProvider(self.cfg, proc=self.proc).live())

    def test_a_summary_run_is_not_a_card(self):
        self.peer(10, "summary", claude.helper_dir(self.cfg), "sdk-cli")
        self.peer(11, "real", "/tmp/project", "sdk-cli")
        self.assertEqual(self.listed(), ["real"])

    def test_a_terminal_session_that_happens_to_sit_there_is_still_a_card(self):
        self.peer(10, "someone", claude.helper_dir(self.cfg), "cli")
        self.assertEqual(self.listed(), ["someone"])

    def test_it_is_not_in_the_log_either(self):
        # `log.peers` reads the real /proc, so the two records are this test's
        # own process and its parent, alive by construction.
        import log
        for pid, sid, cwd in ((os.getpid(), "summary", claude.helper_dir(self.cfg)),
                              (os.getppid(), "real", "/tmp/project")):
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            (self.cfg / "sessions" / f"{pid}.json").write_text(json.dumps(
                {"pid": pid, "sessionId": sid, "kind": "interactive", "entrypoint": "sdk-cli",
                 "status": "busy", "procStart": start, "cwd": str(cwd), "name": sid}))
        self.assertEqual([r["sessionId"] for r in log.peers(self.cfg).values()], ["real"])


if __name__ == "__main__":
    unittest.main()
