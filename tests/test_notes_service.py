"""The real notes search: one call to the notes service, made on a click.

The service is a stand-in on a port of its own (port 0, loopback): it speaks
the part of MCP's streamable HTTP that one search uses, and keeps what it was
sent. No test reaches the real service, and no hit here is text from the
brain -- the notes are invented, and so are the key and the address.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notes
from test_notes_route import Route

KEY = "Bearer invented-key-0123456789"
SESSION = "session-1"


def service_hit(n):
    return {"score": 0.9 - n / 100, "memory_id": f"m{n}", "source_instance": "invented", "file_type": "md",
            "original_location": f"Clients/acme/kickoff-notes-{n}.md", "chunk_index": 0,
            "chunk_text": f"Invented words {n}."}


class Service:
    """A notes service that can be told how to misbehave. `sent` is what reached it."""
    def __init__(self, hits=None):
        self.hits = [service_hit(n) for n in range(1, 6)] if hits is None else hits
        self.sent = []                      # (method, lowercased headers, body or None)
        self.stream = False                 # answer as an event stream, not as JSON
        self.structured = True              # hits in structuredContent as well as in content
        self.status = None                  # answer every POST with this status
        self.hangup = self.garbage = self.rpc_error = self.is_error = False
        self.odd = None                     # a result of this shape, instead of the hits
        self.raw = None                     # these exact bytes, as the answer to the search
        self.garbage_start = False          # a page that is not the service, in answer to the first call
        self.delete_hangup = False          # ends no session: a service may refuse to
        self.redirect = None
        self.delay = 0.0
        self.httpd = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/mcp"

    def searches(self):
        return [body for _, _, body in self.sent if body and body.get("method") == "tools/call"]

    def start(self, case):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def say(self, status, body=b"", headers=()):
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def answer(self, message, headers=()):
                text = json.dumps(message)
                if service.stream:
                    return self.say(200, f"event: message\ndata: {text}\n\n".encode(),
                                    [("Content-Type", "text/event-stream"), *headers])
                self.say(200, text.encode(), [("Content-Type", "application/json"), *headers])

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
                service.sent.append(("POST", {k.lower(): v for k, v in self.headers.items()}, body))
                if service.hangup:
                    self.close_connection = True
                    return
                if service.redirect:
                    return self.say(302, headers=[("Location", service.redirect)])
                if service.status:
                    return self.say(service.status)
                method, ident = body.get("method"), body.get("id")
                if method == "initialize" and service.garbage_start:
                    return self.say(200, b"<html>sign in</html>", [("Content-Type", "text/html")])
                if method == "initialize":
                    return self.answer({"jsonrpc": "2.0", "id": ident, "result": {
                        "protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "invented"}}},
                        [("mcp-session-id", SESSION)])
                if method != "tools/call":
                    return self.say(202)
                time.sleep(service.delay)
                if service.raw is not None:
                    return self.say(200, service.raw, [("Content-Type", "application/json")])
                if service.garbage:
                    return self.say(200, b"<html>not json</html>", [("Content-Type", "text/html")])
                if service.rpc_error:
                    return self.answer({"jsonrpc": "2.0", "id": ident, "error": {"code": -32000, "message": "boom"}})
                if service.odd is not None:
                    return self.answer({"jsonrpc": "2.0", "id": ident, "result": service.odd})
                if service.is_error:
                    return self.answer({"jsonrpc": "2.0", "id": ident, "result": {
                        "content": [{"type": "text", "text": "embedding failed inside"}], "isError": True}})
                result = {"content": [{"type": "text", "text": json.dumps(h)} for h in service.hits],
                          "isError": False}
                if service.structured:
                    result["structuredContent"] = {"result": service.hits}
                self.answer({"jsonrpc": "2.0", "id": ident, "result": result})

            def do_DELETE(self):
                service.sent.append(("DELETE", {k.lower(): v for k, v in self.headers.items()}, None))
                if service.delete_hangup:
                    self.close_connection = True
                    return
                self.say(200)

        class Quiet(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass                        # a client that gave up is the point of one test

        self.httpd = Quiet(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        case.addCleanup(self.httpd.server_close)
        case.addCleanup(self.httpd.shutdown)
        return self


def configure(case, url, auth=KEY, mode=0o600):
    """A notes config file of the test's own, and the variable that points at it."""
    tmp = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, tmp, True)
    path = tmp / "agentview-brain.env"
    path.write_text(f"BRAIN_URL={url}\nBRAIN_AUTH={auth}\n")
    path.chmod(mode)
    env = mock.patch.dict(os.environ, {notes.ENV_VAR: str(path)})
    env.start()
    case.addCleanup(env.stop)
    return path


class Search(unittest.TestCase):
    def setUp(self):
        self.service = Service().start(self)
        configure(self, self.service.url)

    def test_the_key_goes_as_the_authorization_header_exactly_as_written(self):
        notes.search("Loom Prints reports.")
        self.assertTrue(self.service.sent)
        for kind, headers, _ in self.service.sent:
            self.assertEqual(headers["authorization"], KEY, kind)

    def test_it_asks_rag_search_for_three_hits_on_the_query(self):
        notes.search("Loom   Prints reports.")
        self.assertEqual([s["params"] for s in self.service.searches()],
                         [{"name": "rag_search", "arguments": {"query": "Loom Prints reports.", "top_k": 3}}])

    def test_the_top_three_come_back_as_a_title_a_path_and_a_snippet(self):
        got = notes.search("Loom")
        self.assertEqual(got, {"ok": True, "hits": [
            {"title": f"kickoff-notes-{n}", "path": f"Clients/acme/kickoff-notes-{n}.md",
             "snippet": f"Invented words {n}."} for n in (1, 2, 3)]})

    def test_an_event_stream_answer_reads_the_same(self):
        self.service.stream = True
        self.assertEqual([h["path"] for h in notes.search("Loom")["hits"]],
                         [f"Clients/acme/kickoff-notes-{n}.md" for n in (1, 2, 3)])

    def test_hits_that_come_only_as_content_read_the_same(self):
        self.service.structured = False
        self.assertEqual(len(notes.search("Loom")["hits"]), 3)

    def test_hits_in_one_text_block_read_the_same_whichever_way_the_block_holds_them(self):
        hits = [service_hit(n) for n in range(1, 5)]
        for block in (hits, {"result": hits}):
            with self.subTest(block=type(block).__name__):
                self.service.odd = {"content": [{"type": "text", "text": json.dumps(block)}], "isError": False}
                self.assertEqual([h["path"] for h in notes.search("Loom")["hits"]],
                                 [f"Clients/acme/kickoff-notes-{n}.md" for n in (1, 2, 3)])

    def test_a_block_that_is_not_text_is_left_out(self):
        text = {"type": "text", "text": json.dumps(service_hit(1))}
        self.service.odd = {"content": [{"type": "image", "data": "x", "mimeType": "image/png"}, text],
                            "isError": False}
        self.assertEqual([h["path"] for h in notes.search("Loom")["hits"]], ["Clients/acme/kickoff-notes-1.md"])

    def test_no_hits_is_an_empty_answer_not_a_failure(self):
        self.service.hits = []
        self.assertEqual(notes.search("Loom"), {"ok": True, "hits": []})

    def test_something_that_is_not_a_hit_is_left_out(self):
        self.service.hits = ["not a hit", None, 5, service_hit(1)]
        self.assertEqual([h["path"] for h in notes.search("Loom")["hits"]], ["Clients/acme/kickoff-notes-1.md"])

    def test_an_empty_list_is_no_hits_in_every_shape_it_comes_in(self):
        for odd in ({"content": [{"type": "text", "text": "[]"}], "isError": False},
                    {"content": [{"type": "text", "text": '{"result": []}'}], "isError": False},
                    {"content": [], "structuredContent": {"result": []}, "isError": False},
                    {"content": [{"type": "text", "text": "[]"}, {"type": "text", "text": "[]"}], "isError": False}):
            with self.subTest(odd=odd):
                self.service.odd = odd
                self.assertEqual(notes.search("Loom"), {"ok": True, "hits": []})

    def test_a_hit_among_objects_that_are_none_is_still_found(self):
        self.service.odd = {"content": [{"type": "text", "text": json.dumps([{}, {"score": 1}, service_hit(1)])}],
                            "isError": False}
        self.assertEqual([h["path"] for h in notes.search("Loom")["hits"]], ["Clients/acme/kickoff-notes-1.md"])

    def test_a_hit_without_a_location_is_still_a_hit(self):
        self.service.hits = [{"score": 0.5, "chunk_text": "Words."}]
        self.assertEqual(notes.search("Loom")["hits"], [{"title": "", "path": "", "snippet": "Words."}])

    def test_a_hit_without_a_text_is_still_a_hit(self):
        self.service.hits = [{"score": 0.5, "original_location": "Clients/acme/kickoff-notes-9.md"}]
        self.assertEqual(notes.search("Loom")["hits"],
                         [{"title": "kickoff-notes-9", "path": "Clients/acme/kickoff-notes-9.md", "snippet": ""}])

    def test_the_session_is_carried_and_ended(self):
        notes.search("Loom")
        later = [h for _, h, b in self.service.sent if b and b.get("method") != "initialize"]
        self.assertTrue(later)
        for headers in later:
            self.assertEqual(headers.get("mcp-session-id"), SESSION)
        kind, headers, _ = self.service.sent[-1]
        self.assertEqual((kind, headers.get("mcp-session-id")), ("DELETE", SESSION))

    def test_a_service_that_will_not_end_the_session_still_gives_its_hits(self):
        self.service.delete_hangup = True
        self.assertEqual(len(notes.search("Loom")["hits"]), 3)

    def test_nothing_is_asked_until_a_click(self):
        notes.settings()
        notes.searcher()
        self.assertEqual(self.service.sent, [])


class Trouble(unittest.TestCase):
    """Whatever goes wrong, the click gets a reason, and the reason says neither where the service is,
    what the key is, nor what the service said."""
    def setUp(self):
        self.service = Service().start(self)
        configure(self, self.service.url)

    def refused(self):
        got = notes.search("Loom")
        self.assertFalse(got["ok"], got)
        self.assertTrue(got["reason"])
        for secret in (KEY, "invented-key", "127.0.0.1", str(self.service.httpd.server_port), "embedding failed",
                       "boom", "not json"):
            self.assertNotIn(secret, got["reason"])
        return got["reason"]

    def test_a_refused_key_says_so(self):
        self.service.status = 401
        self.assertEqual(self.refused(), "the notes service refused the key")

    def test_another_status_is_named(self):
        self.service.status = 503
        self.assertEqual(self.refused(), "the notes service answered 503")

    def test_a_service_that_hangs_up_is_unreachable(self):
        self.service.hangup = True
        self.assertIn("unreachable", self.refused())

    def test_a_service_that_reports_an_error(self):
        self.service.rpc_error = True
        self.assertEqual(self.refused(), "the notes service reported an error")

    def test_a_search_that_failed_on_the_service(self):
        self.service.is_error = True
        self.assertEqual(self.refused(), "the notes search failed on the service")

    def test_an_answer_that_is_not_one(self):
        self.service.garbage = True
        self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_a_result_of_a_shape_this_code_does_not_know_is_not_no_hits(self):
        for odd in ({}, {"content": 5}, {"content": True}, {"content": {"a": 1}}, {"content": "abc"},
                    {"structuredContent": 5}, {"structuredContent": {"result": 5}, "content": None}):
            with self.subTest(odd=odd):
                self.service.odd = odd
                self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_a_text_block_that_is_not_hits_is_an_answer_not_understood(self):
        for text in ("Nothing matched, sorry.", "5", '"x"'):
            with self.subTest(text=text):
                self.service.odd = {"content": [{"type": "text", "text": text}], "isError": False}
                self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_an_object_that_is_no_hit_is_an_answer_not_understood_not_one_blank_hit(self):
        # A hit has a location or a text. An empty object, a wrapper under another name, or a
        # location that is not text is something this code does not know.
        wrapped = json.dumps({"results": [service_hit(1)], "total": 1})
        for text in ("{}", wrapped, '{"result": "x"}', '[{}, {"score": 1}]', '{"original_location": 5}'):
            with self.subTest(text=text):
                self.service.odd = {"content": [{"type": "text", "text": text}], "isError": False}
                self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_structured_content_with_nothing_that_is_a_hit_is_an_answer_not_understood(self):
        for found in ([{}], ["a", 5], [{"results": []}]):
            with self.subTest(found=found):
                self.service.odd = {"structuredContent": {"result": found},
                                    "content": [{"type": "text", "text": "{}"}], "isError": False}
                self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_an_answer_nested_deeper_than_a_decoder_can_read_is_an_answer_not_understood(self):
        deep_list = "[" * 100000 + "]" * 100000
        deep_object = '{"a":' * 100000 + "1" + "}" * 100000
        for name, odd, raw in (
                ("in a text block", {"content": [{"type": "text", "text": deep_list}], "isError": False}, None),
                ("in the message", None, deep_object.encode()),
                ("in an event stream", None, b"event: message\ndata: " + deep_object.encode() + b"\n\n")):
            with self.subTest(name):
                self.service.odd, self.service.raw = odd, raw
                self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")

    def test_a_first_answer_that_is_not_the_service_ends_it_there(self):
        self.service.garbage_start = True
        self.assertEqual(self.refused(), "the notes service gave an answer this code does not know")
        self.assertEqual(self.service.searches(), [])

    def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(self):
        elsewhere = Service().start(self)
        self.service.redirect = elsewhere.url
        self.assertEqual(self.refused(), "the notes service answered 302")
        self.assertEqual(elsewhere.sent, [])

    def test_a_service_that_is_too_slow_is_given_up_on(self):
        self.service.delay = 1.5
        with mock.patch.object(notes, "CALL_TIMEOUT", 0.3):
            began = time.monotonic()
            self.assertIn("unreachable", self.refused())
        self.assertLess(time.monotonic() - began, 1.2)

    def test_nothing_listening_is_unreachable(self):
        gone = Service().start(self)
        url = gone.url
        gone.httpd.shutdown()
        gone.httpd.server_close()
        configure(self, url)
        self.assertIn("unreachable", self.refused())


class Clicked(Route):
    """The whole chain on a test server: a click, the config file, the service."""
    def test_a_click_returns_three_hits_from_the_service_and_polling_asks_nobody(self):
        service = Service().start(self)
        configure(self, service.url)
        for _ in range(3):
            self.poll()
        self.assertEqual(service.sent, [])
        status, got = self.post("/api/notes", {"query": "Loom Prints reports."})
        self.assertEqual((status, got["ok"], len(got["hits"])), (200, True, 3))
        self.assertEqual(len(service.searches()), 1)

    def test_a_click_with_no_config_asks_nobody(self):
        service = Service().start(self)
        status, got = self.post("/api/notes", {"query": "Loom"})
        self.assertEqual((status, got), (200, {"ok": False, "reason": "notes search is not set up here"}))
        self.assertEqual(service.sent, [])


class Settings(unittest.TestCase):
    def test_a_header_value_with_a_control_character_is_refused_without_being_said(self):
        for bad in ("Bearer a\x00b", "Bearer a\x7fb", "Bearer é"):
            path = configure(self, "http://127.0.0.1:1/mcp", auth=bad)
            with self.assertRaises(notes.Unavailable) as caught:
                notes.settings(path)
            self.assertNotIn("Bearer", str(caught.exception))

    def test_an_address_that_is_no_url_is_refused_without_being_said(self):
        for bad in ("localhost", "ftp://example.test/x", "http://", "http://host:notaport/x"):
            path = configure(self, bad)
            with self.assertRaises(notes.Unavailable) as caught:
                notes.settings(path)
            self.assertIn("BRAIN_URL", str(caught.exception))
            self.assertNotIn(bad, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
