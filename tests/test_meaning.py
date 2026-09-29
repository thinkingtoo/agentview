import json
import math
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archive
import embedder
from test_archive import KETTLE, OTHER, SID, Home, said, typed

# A made-up embedder that speaks the real one's contract. Its "meaning" is a
# handful of concepts, each with the words that say it, so a query can share
# no word with a passage and still land on it -- the whole point of ticket 04.
CONCEPTS = [
    {"kettle", "teapot", "boil", "boiling", "steam", "spout"},
    {"whistle", "whistles", "sings", "singing", "resonance", "shrill"},
    {"copper", "metal", "conducts", "aluminium", "heat"},
    {"garden", "tap", "drips", "hose", "tidy"},
    {"chime", "bell", "ring", "rang", "sound", "silent"},
    {"pipes", "plumbing", "plumber"},
]
KEY = "test-key"


def meaning_of(text, dims, question=False):
    words = [w.strip(".,?!:;\"'").lower() for w in text.split()]
    vec = [0.0] * dims
    for w in words:
        for axis, concept in enumerate(CONCEPTS):
            if w in concept:
                vec[axis] += 1.0
    # Nothing is a zero vector. What means nothing lands on an axis of its own,
    # one for questions and one for passages, so two such texts are unrelated.
    vec[dims - 1 if question else dims - 2] += 0.05
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


class FakeEmbedder:
    """The embedder's HTTP contract on a throwaway port, recording each call."""

    def __init__(self, model="google/embeddinggemma-300m", dims=8):
        self.model, self.dims, self.calls, self.down, self.requests = model, dims, [], False, 0
        self.rubbish = None      # what to put in a vector instead of numbers
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorised(self):
                if self.headers.get("X-API-Key") != KEY:
                    self._json(401, {"detail": "Invalid or missing API key"})
                    return False
                return True

            def do_GET(self):
                fake.requests += 1
                if self.path == "/api/v1/model" and self._authorised():
                    fake.calls.append(("model", None))
                    self._json(200, {"model": fake.model, "dimensions": fake.dims,
                                     "asymmetric": True, "max_len": 2048, "max_batch": 100,
                                     "query_prompt": "task: search result | query: ",
                                     "document_prompt": "title: none | text: "})

            def do_POST(self):
                fake.requests += 1
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if not self._authorised():
                    return
                if fake.down:
                    self._json(503, {"detail": "not ready"})
                elif self.path == "/api/v1/embed/text":
                    fake.calls.append(("query", body["text"]))
                    vec = meaning_of(body["text"], fake.dims, question=True)
                    self._json(200, {"vector": [fake.rubbish] * fake.dims if fake.rubbish else vec,
                                     "dimensions": fake.dims})
                elif self.path == "/api/v1/embed/batch":
                    if len(body["texts"]) > 100:
                        self._json(422, {"detail": "batch exceeds the 100 cap; split it"})
                        return
                    fake.calls.append(("documents", body["texts"]))
                    self._json(200, {"vectors": [[fake.rubbish] * fake.dims if fake.rubbish else
                                                 meaning_of(t, fake.dims) for t in body["texts"]],
                                     "dimensions": fake.dims, "count": len(body["texts"])})
                else:
                    self._json(404, {"detail": "Not Found"})

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.01,), daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def client(self):
        return embedder.Embedder(self.url, KEY)

    def sent(self, kind):
        return [payload for k, payload in self.calls if k == kind]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Meaning(Home):
    def setUp(self):
        super().setUp()
        self.fake = FakeEmbedder()

    def tearDown(self):
        self.fake.close()
        super().tearDown()

    def update(self, emb="fake"):
        return archive.update(path=self.db, root=self.projects, cfg=self.root, logs=self.logs,
                              emb=self.fake.client() if emb == "fake" else emb)


class Embedding(Meaning, unittest.TestCase):
    def test_stored_passages_go_through_the_document_endpoint(self):
        self.write(SID, KETTLE)
        run = self.update()
        batches = self.fake.sent("documents")
        self.assertEqual(sorted(t for b in batches for t in b), sorted([
            "Why does the kettle whistle?\n\nSteam escapes through the spout.\n\nThe whistle is a resonance.",
            "Done for the peer.",
            "/rem kettle notes\n\nSaved the kettle notes.",
            "pasted words about copper\n\nCopper conducts heat well."]))
        self.assertEqual(self.fake.sent("query"), [])
        self.assertEqual(run["embedded"], 4)

    def test_a_batch_never_holds_more_than_a_hundred_passages(self):
        records = []
        for i in range(250):
            records += [typed(2 * i, f"question {i}"), said(2 * i + 1, f"answer {i}")]
        self.write(SID, records)
        self.update()
        self.assertEqual([len(b) for b in self.fake.sent("documents")], [100, 100, 50])


class Identity(Meaning, unittest.TestCase):
    def vectors(self):
        return self.rows("SELECT passage, length(vec) FROM vectors ORDER BY passage")

    def test_vectors_are_stored_in_the_index_with_the_models_identity(self):
        self.write(SID, KETTLE)
        self.update()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors"), [(4,)])
        self.assertEqual(self.rows("SELECT DISTINCT length(vec) FROM vectors"), [(8 * 4,)])
        ident = json.loads(self.rows("SELECT value FROM meta WHERE key='embedder'")[0][0])
        self.assertEqual((ident["model"], ident["dimensions"]), ("google/embeddinggemma-300m", 8))

    def test_a_different_model_rebuilds_every_vector_and_never_mixes(self):
        self.write(SID, KETTLE)
        self.update()
        old = self.rows("SELECT vec FROM vectors")
        self.fake.model, self.fake.dims = "another/model", 6
        self.fake.calls.clear()
        run = self.update()
        self.assertEqual(run["embedded"], 4)
        self.assertEqual(sum(len(b) for b in self.fake.sent("documents")), 4)
        self.assertEqual(self.rows("SELECT DISTINCT length(vec) FROM vectors"), [(6 * 4,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors"), [(4,)])
        self.assertNotEqual(old, self.rows("SELECT vec FROM vectors"))

    def test_the_same_model_is_not_embedded_again(self):
        self.write(SID, KETTLE)
        self.update()
        self.fake.calls.clear()
        self.assertEqual(self.update()["embedded"], 0)
        self.assertEqual(self.fake.sent("documents"), [])

    def test_only_what_changed_is_embedded_and_a_gone_passage_takes_its_vector(self):
        path = self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "unrelated", sid=OTHER), said(2, "Noted.", sid=OTHER)])
        self.update()
        self.fake.calls.clear()
        # The open exchange grows, and a new one starts: two passages to embed.
        self.write(SID, [said(20, "Also aluminium."), typed(21, "and glass?"),
                         said(22, "Glass is slow.")], mode="a")
        self.assertEqual(self.update()["embedded"], 2)
        self.assertEqual([t for b in self.fake.sent("documents") for t in b],
                         ["pasted words about copper\n\nCopper conducts heat well.\n\nAlso aluminium.",
                          "and glass?\n\nGlass is slow."])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors"), [(6,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors WHERE passage NOT IN"
                                   " (SELECT id FROM passages)"), [(0,)])
        path.unlink()
        self.update()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors"), [(1,)])

    def test_only_passage_text_is_sent(self):
        self.write(SID, KETTLE + [{"type": "agent-name", "agentName": "kettle-work", "sessionId": SID}])
        self.update()
        sent = json.dumps(self.fake.sent("documents"))
        for private in ("maple", "alice", "kettle-work", "Kettle physics", SID, str(self.root)):
            self.assertNotIn(private, sent)


CHIME = "00000000-0000-4000-8000-0000000000c1"
METAL = "00000000-0000-4000-8000-0000000000c2"
PIPES = "00000000-0000-4000-8000-0000000000c3"
QUESTION = "the session where the chime did not ring"


class Finding(Meaning, unittest.TestCase):
    """Search through the embedder, over conversations made up for it."""

    def setUp(self):
        super().setUp()
        self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "tidy the garden", sid=OTHER),
                           said(2, "Done. The tap still drips.", sid=OTHER)])
        # Says "bell" and "silent", never "chime" or "ring".
        self.write(CHIME, [typed(1, "why was the bell silent this morning?", sid=CHIME),
                           said(2, "The volume was muted, so the sound never played.", sid=CHIME)])
        # Copper never appears; heat and metal do.
        self.write(METAL, [typed(1, "does aluminium conduct heat?", sid=METAL),
                           said(2, "Yes, it is a metal that conducts heat.", sid=METAL)])
        self.write(PIPES, [typed(1, "copper copper copper pipes", sid=PIPES),
                           said(2, "Copper pipes, yes.", sid=PIPES)])
        self.update()
        self.fake.calls.clear()

    def find(self, words, emb="fake", **kw):
        return archive.find(words, path=self.db, emb=self.fake.client() if emb == "fake" else emb, **kw)

    def test_a_paraphrase_finds_a_conversation_that_shares_no_keyword(self):
        self.assertEqual(archive.search(QUESTION, path=self.db), [])
        hits, meaning = self.find(QUESTION)
        self.assertEqual(hits[0]["id"], CHIME)
        self.assertEqual(hits[0]["via"], "meaning")
        self.assertIn("bell silent", hits[0]["passage"]["prompt"])
        self.assertEqual(meaning["state"], "on")

    def test_the_question_goes_through_the_query_endpoint_and_only_that(self):
        self.find(QUESTION)
        self.assertEqual(self.fake.sent("query"), [QUESTION])
        self.assertEqual(self.fake.sent("documents"), [])

    def test_the_two_lists_are_merged_one_row_per_conversation(self):
        hits, _ = self.find("copper")
        ids = [h["id"] for h in hits]
        self.assertEqual(len(ids), len(set(ids)))
        # Found by both -- the words and the meaning -- outranks meaning alone.
        by = {h["id"]: h["via"] for h in hits}
        self.assertEqual((by[PIPES], by[SID], by[METAL]), ("both", "both", "meaning"))
        self.assertEqual(set(ids[:2]), {PIPES, SID})
        self.assertEqual(ids[2], METAL)
        self.assertNotIn(OTHER, ids)

    def test_a_keyword_hit_keeps_its_marked_passage(self):
        hits, _ = self.find("copper")
        self.assertIn("\x02copper\x03", next(h for h in hits if h["id"] == PIPES)["passage"]["prompt"])

    def test_a_meaning_hit_is_a_plain_passage_with_the_usual_fields(self):
        hits, _ = self.find("copper")
        hit = next(h for h in hits if h["id"] == METAL)
        self.assertEqual(set(hit["passage"]), {"exchange", "piece", "at", "uuid", "prompt", "reply"})
        self.assertNotIn("\x02", hit["passage"]["prompt"] + hit["passage"]["reply"])
        self.assertEqual((hit["cwd"], hit["live"]), ("/home/alice/Projects/maple", False))

    def test_a_question_that_means_nothing_finds_nothing(self):
        hits, meaning = self.find("zzz qqq")
        self.assertEqual(hits, [])
        self.assertEqual(meaning["state"], "on")

    def test_no_words_never_reach_the_embedder(self):
        self.fake.requests = 0
        self.assertEqual(self.find("  ")[0], [])
        self.assertEqual(self.find('""')[0], [])
        self.assertEqual(self.fake.requests, 0)


class EmbedderOff(Meaning, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "tidy the garden", sid=OTHER),
                           said(2, "Done. The copper tap still drips.", sid=OTHER)])
        self.update()

    def find(self, words, emb):
        return archive.find(words, path=self.db, emb=emb)

    def keyword_ids(self):
        return [h["id"] for h in archive.search("copper", path=self.db)]

    def test_an_unreachable_embedder_still_gives_the_keyword_hits(self):
        began = time.monotonic()
        hits, meaning = self.find("copper", embedder.Embedder("http://127.0.0.1:1", KEY))
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual([h["id"] for h in hits], self.keyword_ids())
        self.assertTrue(hits)
        self.assertEqual(meaning["state"], "off")
        self.assertIn("unreachable", meaning["why"])
        self.assertNotIn("127.0.0.1", meaning["why"])

    def test_an_embedder_that_accepts_and_never_answers_costs_one_short_wait(self):
        quiet = socket.socket()
        quiet.bind(("127.0.0.1", 0))
        quiet.listen(5)                      # accepts the connection, never replies
        self.addCleanup(quiet.close)
        emb = embedder.Embedder(f"http://127.0.0.1:{quiet.getsockname()[1]}", KEY)
        with mock.patch.object(embedder, "QUERY_TIMEOUT", 0.3):
            began = time.monotonic()
            hits, meaning = self.find("copper", emb)
            first = time.monotonic() - began
            began = time.monotonic()
            self.find("copper", emb)
            second = time.monotonic() - began
        self.assertTrue(hits)
        self.assertEqual(meaning["state"], "off")
        self.assertIn("unreachable", meaning["why"])
        self.assertGreater(first, 0.25)
        self.assertLess(second, 0.25)

    def test_a_vector_that_is_not_numbers_is_off_not_a_crash(self):
        self.fake.rubbish = "x"
        hits, meaning = self.find("copper", self.fake.client())
        self.assertEqual([h["id"] for h in hits], self.keyword_ids())
        self.assertEqual(meaning["state"], "off")
        self.assertIn("cannot use", meaning["why"])

    def test_vectors_that_are_not_numbers_are_never_stored(self):
        self.fake.rubbish = "x"
        self.fake.model = "another/model"       # so that everything is embedded again
        run = self.update()
        self.assertEqual(run["embedded"], 0)
        self.assertTrue(run["meaning"].startswith("off: "))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM vectors"), [(0,)])

    def test_an_embedder_that_is_not_ready_is_off_too(self):
        self.fake.down = True
        hits, meaning = self.find("copper", self.fake.client())
        self.assertEqual([h["id"] for h in hits], self.keyword_ids())
        self.assertEqual(meaning["state"], "off")

    def test_after_a_failure_it_is_left_alone_for_a_while(self):
        emb = embedder.Embedder("http://127.0.0.1:1", KEY)
        emb.retry_at = 0
        with mock.patch.object(embedder.http.client, "HTTPConnection",
                               wraps=embedder.http.client.HTTPConnection) as wire:
            self.find("copper", emb)
            self.find("copper again", emb)
            self.find("and again", emb)
        self.assertEqual(wire.call_count, 1)

    def test_no_embedder_configured_is_off_with_the_reason(self):
        hits, meaning = self.find("copper", embedder.load(self.root / "missing.env"))
        self.assertEqual([h["id"] for h in hits], self.keyword_ids())
        self.assertEqual(meaning, {"state": "off", "why": "no embedder is configured"})

    def test_no_embedder_at_all_is_off_too(self):
        hits, meaning = self.find("copper", None)
        self.assertTrue(hits)
        self.assertEqual(meaning["state"], "off")

    def test_no_vectors_yet_is_off_and_says_the_next_update_builds_them(self):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM meta WHERE key='embedder'")
        con.execute("DELETE FROM vectors")
        con.commit()
        con.close()
        hits, meaning = self.find("copper", self.fake.client())
        self.assertTrue(hits)
        self.assertEqual(meaning["state"], "off")
        self.assertIn("next update", meaning["why"])

    def test_vectors_from_another_model_are_never_compared(self):
        self.fake.model = "another/model"
        self.fake.calls.clear()
        emb = self.fake.client()
        hits, meaning = self.find("copper", emb)
        self.assertEqual([h["id"] for h in hits], self.keyword_ids())
        self.assertEqual(meaning["state"], "off")
        self.assertIn("another model", meaning["why"])
        self.assertEqual(self.fake.sent("query"), [])

    def test_an_update_with_the_embedder_down_still_indexes_by_keyword(self):
        self.fake.down = True
        self.write(OTHER, [typed(1, "tidy the garden", sid=OTHER),
                           said(2, "Done. The copper tap still drips.", sid=OTHER),
                           typed(3, "and the hedge", sid=OTHER), said(4, "Hedge trimmed.", sid=OTHER)])
        run = self.update()
        self.assertEqual((run["changed"], run["embedded"]), (1, 0))
        self.assertTrue(run["meaning"].startswith("off: "))
        self.assertGreater(run["unembedded"], 0)
        self.assertEqual(len(archive.search("hedge", path=self.db)), 1)
        # And when it is back, the missing passages are embedded, and only those.
        self.fake.down = False
        self.fake.calls.clear()
        run = self.update()
        self.assertEqual((run["meaning"], run["unembedded"]), ("on", 0))
        self.assertEqual(sum(len(b) for b in self.fake.sent("documents")), run["embedded"])

    def test_an_update_without_an_embedder_says_so(self):
        run = self.update(emb=None)
        self.assertEqual((run["embedded"], run["meaning"]), (0, "off: no embedder is configured"))


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / "embedder.env"

    def tearDown(self):
        shutil.rmtree(self.dir)

    def make(self, text, mode=0o600):
        self.file.write_text(text)
        self.file.chmod(mode)

    def test_the_address_and_key_come_from_the_local_file(self):
        self.make("# a comment\nEMBEDDER_URL=http://example.invalid:9\nEMBEDDER_API_KEY='abc'\n")
        emb = embedder.load(self.file)
        self.assertEqual((emb.base, emb.key, emb.problem), ("http://example.invalid:9", "abc", ""))

    def test_a_url_that_already_ends_in_the_api_path_is_taken_as_the_base(self):
        self.make("EMBEDDER_URL=http://example.invalid:9/api/v1\nEMBEDDER_API_KEY=k\n")
        self.assertEqual(embedder.load(self.file).base, "http://example.invalid:9")

    def test_a_key_others_can_read_is_not_used(self):
        self.make("EMBEDDER_URL=http://example.invalid:9\nEMBEDDER_API_KEY=k\n", mode=0o644)
        with self.assertRaisesRegex(embedder.Unavailable, "chmod 600"):
            embedder.load(self.file).identity()

    def test_a_file_missing_the_key_is_not_used(self):
        self.make("EMBEDDER_URL=http://example.invalid:9\n")
        with self.assertRaisesRegex(embedder.Unavailable, "lacks"):
            embedder.load(self.file).identity()

    def test_the_path_can_be_named_in_the_environment(self):
        with mock.patch.dict(os.environ, {embedder.ENV_VAR: str(self.file)}):
            self.assertEqual(embedder.config_path(), self.file)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(embedder.ENV_VAR, None)
            self.assertEqual(embedder.config_path(), Path(embedder.DEFAULT_ENV).expanduser())

    def test_the_same_file_gives_the_same_embedder_so_the_back_off_outlives_a_request(self):
        self.make("EMBEDDER_URL=http://example.invalid:9\nEMBEDDER_API_KEY=k\n")
        self.assertIs(embedder.load(self.file), embedder.load(self.file))


class Route(Meaning, unittest.TestCase):
    """The route the page calls, over HTTP, with the embedder named the way a
    real one is: by a local config file."""

    def setUp(self):
        super().setUp()
        self.saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", embedder.ENV_VAR)}
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.root)
        self.env = self.root / "embedder.env"
        self.point_at(self.fake.url)
        self.write(CHIME, [typed(1, "why was the bell silent this morning?", sid=CHIME),
                           said(2, "The volume was muted, so the sound never played.", sid=CHIME)])
        self.write(OTHER, [typed(1, "the chime on the fleet page", sid=OTHER),
                           said(2, "The chime is a two-stroke tone.", sid=OTHER)])
        self.update()
        import server
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.01,), daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def point_at(self, url):
        self.env.write_text(f"EMBEDDER_URL={url}\nEMBEDDER_API_KEY={KEY}\n")
        self.env.chmod(0o600)
        os.environ[embedder.ENV_VAR] = str(self.env)

    def get(self, query):
        url = f"http://127.0.0.1:{self.httpd.server_port}/api/search?q={urllib.parse.quote(query)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)

    def test_a_paraphrase_finds_the_conversation_and_the_answer_says_meaning_is_on(self):
        got = self.get(QUESTION)
        self.assertEqual(got["results"][0]["id"], CHIME)
        self.assertEqual(got["results"][0]["via"], "meaning")
        self.assertEqual(got["meaning"]["state"], "on")

    def test_with_the_embedder_unreachable_keywords_still_answer_and_the_answer_says_so(self):
        self.point_at("http://127.0.0.1:1")
        began = time.monotonic()
        got = self.get("chime")
        self.assertLess(time.monotonic() - began, 3)
        self.assertEqual([h["id"] for h in got["results"]], [OTHER])
        self.assertEqual(got["results"][0]["via"], "words")
        self.assertEqual(got["meaning"]["state"], "off")
        self.assertIn("unreachable", got["meaning"]["why"])
        self.assertNotIn("127.0.0.1", json.dumps(got["meaning"]))

    def test_with_no_embedder_configured_the_answer_says_so(self):
        self.env.unlink()
        got = self.get("chime")
        self.assertEqual([h["id"] for h in got["results"]], [OTHER])
        self.assertEqual(got["meaning"], {"state": "off", "why": "no embedder is configured"})

    def test_before_the_first_run_there_is_no_index(self):
        self.db.unlink()
        got = self.get("chime")
        self.assertEqual((got["results"], got["index"], got["meaning"]["state"]), ([], None, "off"))


if __name__ == "__main__":
    unittest.main()
