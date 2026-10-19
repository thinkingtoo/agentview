"""The two things a card's text asks of the server: keep a context line of your
own (`/api/context`), and look in your notes on a click (`/api/notes`).

A fake provider stands behind the roster and every store is a throwaway. The
notes searcher is a fake that counts its calls: no test reaches a real search,
and none carries text from the brain -- the hits here are invented. The
notes config path is always a temp file, never `~/.config/tiroir`.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
import log
import notes
import seen
import server
from test_providers import Fake, minimal

LOOM = "repo:example.com/alice/loom"
HOSTILE = "<img src=x onerror=alert(1)>"


class Route(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = self.tmp / "config.json"
        self.config.write_text("{}")
        fake = Fake([minimal(id="a", name="Ilse", cwd="/home/alice/Projects/maple", canJump=True)])
        for target, new in (("fleet.CONFIG", self.config),
                            ("fleet._providers", lambda: [fake]),
                            ("seen.store", lambda: self.tmp / "seen.json"),
                            ("lines.store", lambda: self.tmp / "lines"),
                            ("log.LOG", self.tmp / "events.jsonl"),
                            ("server.restorable", lambda live: None),
                            ("server.closed_now", lambda live: []),
                            ("server.coverage", lambda live: None),
                            ("providers.broken", lambda: {})):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)
        # The notes config is a file that does not exist unless a test writes it.
        self.brain_env = self.tmp / "agentview-brain.env"
        env = mock.patch.dict(os.environ, {notes.ENV_VAR: str(self.brain_env)})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_port}{path}", method="POST",
            data=json.dumps(body).encode(), headers={"X-Fleet": "1"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as err:
            return err.code, None

    def poll(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.httpd.server_port}/api/roster", timeout=10) as r:
            return json.load(r)

    def stored(self):
        return json.loads(self.config.read_text())


class ContextRoute(Route):
    def test_a_line_you_write_is_kept_under_the_projects_identity(self):
        self.assertEqual(self.post("/api/context", {"project": LOOM, "text": "  Prints reports  "})[0], 200)
        self.assertEqual(self.stored()["project_lines"], {LOOM: "Prints reports"})

    def test_a_line_is_one_line_of_bounded_length(self):
        self.post("/api/context", {"project": LOOM, "text": "a\n  b " + "x" * 5000})
        stored = self.stored()["project_lines"][LOOM]
        self.assertTrue(stored.startswith("a b x"))
        self.assertLessEqual(len(stored), 1500)

    def test_the_next_poll_shows_it_as_your_own(self):
        self.post("/api/context", {"project": "folder:maple", "text": "Sells apples"})
        column = self.poll()["columns"][0]
        self.assertEqual((column["context"]["source"], column["context"]["line"]),
                         ("own", "Sells apples"))

    def test_an_empty_line_takes_yours_back(self):
        self.config.write_text(json.dumps({"project_lines": {LOOM: "Prints reports", "folder:maple": "Keep"}}))
        self.post("/api/context", {"project": LOOM, "text": "   "})
        self.assertEqual(self.stored()["project_lines"], {"folder:maple": "Keep"})

    def test_everything_else_in_the_config_stays(self):
        self.config.write_text(json.dumps({"names": {"a": "b"}, "pinned": ["x"], "lines": {"fake:a": "t"}}))
        self.post("/api/context", {"project": LOOM, "text": "Prints reports"})
        got = self.stored()
        self.assertEqual((got["names"], got["pinned"], got["lines"]), ({"a": "b"}, ["x"], {"fake:a": "t"}))

    def test_a_name_that_is_no_identity_is_refused_and_nothing_is_written(self):
        for project in ("loom", "", "nonsense:loom", "track:"):
            self.assertEqual(self.post("/api/context", {"project": project, "text": "x"})[0], 400, project)
        for body in ({"project": LOOM, "text": 5}, {"project": 5, "text": "x"}, {"text": "x"}):
            self.assertEqual(self.post("/api/context", body)[0], 400, body)
        self.assertNotIn("project_lines", self.stored())

    def test_markup_in_your_line_comes_back_as_the_text_it_is(self):
        self.post("/api/context", {"project": "folder:maple", "text": "Sells " + HOSTILE})
        self.assertEqual(self.poll()["columns"][0]["context"]["line"], "Sells " + HOSTILE)


class Searcher:
    """A notes search that counts how often it was asked, and answers what it was told to."""
    def __init__(self, hits=(), raises=None):
        self.hits, self.raises, self.asked = list(hits), raises, []

    def __call__(self, query):
        self.asked.append(query)
        if self.raises:
            raise self.raises
        return self.hits


def hit(n, **over):
    return {"title": f"Note {n}", "path": f"Clients/note-{n}.md", "snippet": f"Invented words {n}.", **over}


class NotesRoute(Route):
    def searching(self, searcher):
        patch = mock.patch("notes.searcher", lambda: searcher)
        patch.start()
        self.addCleanup(patch.stop)
        return searcher

    def test_a_click_asks_once_and_the_top_three_come_back(self):
        found = self.searching(Searcher([hit(n) for n in range(1, 6)]))
        status, got = self.post("/api/notes", {"query": "Loom Prints reports."})
        self.assertEqual((status, got["ok"], [h["title"] for h in got["hits"]]),
                         (200, True, ["Note 1", "Note 2", "Note 3"]))
        self.assertEqual(found.asked, ["Loom Prints reports."])

    def test_polling_the_roster_never_searches(self):
        found = self.searching(Searcher([hit(1)]))
        for _ in range(3):
            self.poll()
        self.assertEqual(found.asked, [])

    def test_with_nothing_set_up_it_says_so_and_asks_nobody(self):
        status, got = self.post("/api/notes", {"query": "Loom"})
        self.assertEqual((status, got), (200, {"ok": False, "reason": "notes search is not set up here"}))

    def test_a_search_that_cannot_be_reached_says_why_and_the_page_goes_on(self):
        self.searching(Searcher(raises=notes.Unavailable("the notes service is unreachable")))
        self.assertEqual(self.post("/api/notes", {"query": "Loom"})[1],
                         {"ok": False, "reason": "the notes service is unreachable"})

    def test_a_search_with_no_hits_is_an_empty_answer_not_a_failure(self):
        self.searching(Searcher([]))
        self.assertEqual(self.post("/api/notes", {"query": "Loom"})[1], {"ok": True, "hits": []})

    def test_the_query_is_a_line_of_bounded_length_and_an_empty_one_asks_nobody(self):
        found = self.searching(Searcher([hit(1)]))
        self.post("/api/notes", {"query": "Loom\nPrints   reports " + "x" * 1000})
        self.assertEqual(len(found.asked), 1)
        self.assertTrue(found.asked[0].startswith("Loom Prints reports x"))
        self.assertLessEqual(len(found.asked[0]), notes.QUERY_MAX)
        self.assertEqual(self.post("/api/notes", {"query": "  \n "})[1],
                         {"ok": False, "reason": "nothing to search for"})
        self.assertEqual(len(found.asked), 1)

    def test_a_request_without_a_text_query_is_refused(self):
        found = self.searching(Searcher([hit(1)]))
        for body in ({}, {"query": 5}, {"query": None}, {"project": LOOM}):
            self.assertEqual(self.post("/api/notes", body)[0], 400, body)
        self.assertEqual(found.asked, [])

    def test_a_hit_is_three_short_texts_and_markup_in_them_stays_text(self):
        self.searching(Searcher([hit(1, title=HOSTILE, snippet="Words " + HOSTILE),
                                 {"title": 5, "path": None, "snippet": ["x"], "score": 0.9},
                                 "not a hit", hit(2, snippet="y" * 5000)]))
        got = self.post("/api/notes", {"query": "Loom"})[1]["hits"]
        self.assertEqual(got[0], {"title": HOSTILE, "path": "Clients/note-1.md", "snippet": "Words " + HOSTILE})
        self.assertEqual(got[1], {"title": "", "path": "", "snippet": ""})
        self.assertEqual(len(got), 3)
        self.assertLessEqual(len(got[2]["snippet"]), notes.SNIPPET_MAX)


class Config(unittest.TestCase):
    """The notes config, like the embedder's: a local file, mode 0600, never in the repo."""
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.path = tmp / "agentview-brain.env"
        env = mock.patch.dict(os.environ, {notes.ENV_VAR: str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def write(self, text, mode=0o600):
        self.path.write_text(text)
        self.path.chmod(mode)

    def reason(self):
        with self.assertRaises(notes.Unavailable) as caught:
            notes.searcher()
        return str(caught.exception)

    def test_no_file_means_not_set_up(self):
        self.assertEqual(self.reason(), "notes search is not set up here")

    def test_a_file_others_can_read_is_refused_and_its_contents_never_said(self):
        self.write("BRAIN_URL=http://example.test:1\nBRAIN_AUTH=Bearer sekrit\n", 0o644)
        why = self.reason()
        self.assertIn("chmod 600", why)
        self.assertNotIn("sekrit", why)
        self.assertNotIn("example.test", why)

    def test_a_file_without_both_settings_is_refused(self):
        self.write("BRAIN_URL=http://example.test:1\n")
        self.assertIn("BRAIN_URL or BRAIN_AUTH", self.reason())
        self.write("BRAIN_AUTH=Bearer sekrit\n")
        why = self.reason()
        self.assertIn("BRAIN_URL or BRAIN_AUTH", why)
        self.assertNotIn("sekrit", why)

    def test_the_old_name_for_the_key_is_not_the_key(self):
        self.write("BRAIN_URL=http://example.test:1\nBRAIN_API_KEY=sekrit\n")
        self.assertIn("BRAIN_URL or BRAIN_AUTH", self.reason())

    def test_a_complete_file_is_read_and_gives_a_search(self):
        self.write("# comment\nBRAIN_URL=http://example.test:1\nBRAIN_AUTH='Bearer sekrit'\n")
        self.assertEqual(notes.settings(), ("http://example.test:1", "Bearer sekrit"))
        self.assertTrue(callable(notes.searcher()))


if __name__ == "__main__":
    unittest.main()
