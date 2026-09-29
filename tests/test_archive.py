import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archive

# A made-up conversation in the shape Claude Code writes, one of every kind
# of record the index must keep or drop. Nothing here comes from a real
# transcript. Each word in capitals is something that must not be indexed.
SID = "00000000-0000-4000-8000-00000000000a"
OTHER = "00000000-0000-4000-8000-00000000000b"


def rec(kind, n, sid=SID, **fields):
    return {"type": kind, "sessionId": sid, "entrypoint": fields.pop("entrypoint", "cli"),
            "cwd": "/home/alice/Projects/maple", "isSidechain": False,
            "uuid": f"u{n}", "timestamp": f"2026-08-10T09:{n:02d}:00.000Z", **fields}


def typed(n, text, sid=SID):
    return rec("user", n, sid, origin={"kind": "human"}, message={"role": "user", "content": text})


def said(n, *parts, sid=SID, **fields):
    content = [{"type": "text", "text": p} if isinstance(p, str) else p for p in parts]
    return rec("assistant", n, sid, message={"role": "assistant", "model": "claude-x",
                                             "content": content}, **fields)


KETTLE = [
    {"type": "mode", "mode": "normal", "sessionId": SID},
    rec("attachment", 1, attachment={"type": "hook_success", "content": "HOOKTEXT"}),
    typed(2, "Why does the kettle whistle?\n<system-reminder>REMINDERTEXT</system-reminder>"),
    said(3, {"type": "thinking", "thinking": "THINKINGTEXT"}, "Steam escapes through the spout."),
    said(4, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "TOOLCALLTEXT"}}),
    rec("user", 5, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "TOOLRESULTTEXT"}]}),
    said(6, "The whistle is a resonance.<system-reminder>REMINDERTEXT</system-reminder>"),
    rec("user", 7, isMeta=True, message={"role": "user", "content": [
        {"type": "text", "text": "SKILLBODYTEXT"}]}),
    rec("user", 8, isMeta=True, origin={"kind": "peer", "from": "uds:x"},
        message={"role": "user", "content": "Another Claude session sent a message:\n"
                 "<cross-session-message from=\"uds:x\">PEERTEXT</cross-session-message>"}),
    said(9, "Done for the peer."),
    typed(10, "<command-message>rem</command-message>\n<command-name>/rem</command-name>\n"
              "<command-args>kettle notes</command-args>"),
    said(11, "Saved the kettle notes."),
    rec("user", 12, message={"role": "user",
                             "content": "<local-command-stdout>LOCALTEXT</local-command-stdout>"}),
    said(13, "SIDECHAINTEXT", isSidechain=True),
    {"type": "ai-title", "aiTitle": "Kettle physics", "sessionId": SID},
    typed(14, '<pasted_content id="ab">\npasted words about copper\n</pasted_content id="ab">'),
    rec("assistant", 15, message={"role": "assistant", "model": "<synthetic>",
                                  "content": [{"type": "text", "text": "SYNTHETICTEXT"}]}),
    said(16, "Copper conducts heat well."),
]
DROPPED = ("HOOKTEXT", "REMINDERTEXT", "THINKINGTEXT", "TOOLCALLTEXT", "TOOLRESULTTEXT",
           "SKILLBODYTEXT", "PEERTEXT", "LOCALTEXT", "SIDECHAINTEXT", "SYNTHETICTEXT",
           "pasted_content", "command-name")


def compact(r):
    """As Claude Code writes a record: no spaces, which the title reader relies on."""
    return json.dumps(r, separators=(",", ":"))


def lines(records):
    return [(i, compact(r).encode()) for i, r in enumerate(records)]


class Home:
    """A throwaway ~/.claude with a projects folder and a peer folder."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.projects = self.root / "projects"
        self.db = self.root / "agentview" / "archive.db"
        self.logs = [self.root / "events.jsonl"]

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, sid, records, folder="-home-alice-Projects-maple", mode="w"):
        path = self.projects / folder / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding="utf-8") as fh:
            for r in records:
                fh.write(compact(r) + "\n")
        return path

    def update(self):
        return archive.update(path=self.db, root=self.projects, cfg=self.root, logs=self.logs)

    def rows(self, sql, *args):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


class Stripping(unittest.TestCase):
    def test_a_passage_is_what_was_typed_and_what_was_said(self):
        exchanges, _ = archive.parse(lines(KETTLE))
        self.assertEqual([e["prompt"] for e in exchanges],
                         ["Why does the kettle whistle?", "", "/rem kettle notes",
                          "pasted words about copper"])
        self.assertEqual(exchanges[0]["reply"],
                         "Steam escapes through the spout.\n\nThe whistle is a resonance.")
        self.assertEqual(exchanges[1]["reply"], "Done for the peer.")
        self.assertEqual(exchanges[3]["reply"], "Copper conducts heat well.")

    def test_machine_text_never_reaches_the_index(self):
        exchanges, _ = archive.parse(lines(KETTLE))
        text = json.dumps(exchanges)
        for word in DROPPED:
            self.assertNotIn(word, text)

    def test_the_conversation_says_where_and_when(self):
        _, facts = archive.parse(lines(KETTLE))
        self.assertEqual(facts["cwd"], "/home/alice/Projects/maple")
        self.assertEqual(facts["first"], "2026-08-10T09:01:00.000Z")
        self.assertEqual(facts["last"], "2026-08-10T09:16:00.000Z")

    def test_words_before_any_prompt_are_an_exchange_of_their_own(self):
        exchanges, _ = archive.parse(lines([said(1, "Resumed and carrying on."),
                                            typed(2, "thanks")]))
        self.assertEqual([(e["prompt"], e["reply"]) for e in exchanges],
                         [("", "Resumed and carrying on."), ("thanks", "")])

    def test_a_long_exchange_is_cut_into_pieces_that_keep_every_word(self):
        reply = " ".join(f"word{i}" for i in range(3000))
        cut = archive.pieces("the question", reply, size=1000)
        self.assertGreater(len(cut), 10)
        self.assertTrue(all(len(p) + len(r) <= 1000 for p, r in cut))
        self.assertEqual(cut[0][0], "the question")
        self.assertEqual(" ".join(r for _, r in cut).split(), reply.split())

    def test_a_short_exchange_is_one_piece(self):
        self.assertEqual(archive.pieces("q", "a"), [("q", "a")])


class Indexing(Home, unittest.TestCase):
    def test_only_interactive_transcripts_are_indexed(self):
        self.write(SID, KETTLE)
        self.write(OTHER, [rec("user", 1, OTHER, entrypoint="sdk-cli", origin={"kind": "human"},
                               message={"role": "user", "content": "kettle from a routine"})])
        sub = self.projects / "-home-alice-Projects-maple" / SID / "subagents" / "agent-1.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps(typed(1, "kettle from a subagent")) + "\n")
        run = self.update()
        self.assertEqual(run["conversations"], 1)
        self.assertEqual(self.rows("SELECT id FROM conversations"), [(SID,)])
        self.assertEqual(self.rows("SELECT entrypoint FROM skipped"), [("sdk-cli",)])
        self.assertEqual(len(archive.search("kettle", path=self.db)), 1)

    def test_the_index_is_as_private_as_the_transcripts(self):
        self.write(SID, KETTLE)
        self.update()
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_an_unchanged_transcript_is_not_read_again(self):
        self.write(SID, KETTLE)
        self.assertEqual(self.update()["changed"], 1)
        self.assertEqual(self.update()["changed"], 0)

    def test_a_growing_conversation_is_read_from_its_last_exchange(self):
        path = self.write(SID, KETTLE)
        self.update()
        before = self.rows("SELECT exchange, prompt, reply FROM passages WHERE exchange < 3 ORDER BY exchange")
        # The open exchange grows, then a new one starts.
        self.write(SID, [said(20, "Also aluminium.")], mode="a")
        self.update()
        self.assertEqual(self.rows("SELECT reply FROM passages WHERE exchange=3"),
                         [("Copper conducts heat well.\n\nAlso aluminium.",)])
        self.write(SID, [typed(21, "and glass?"), said(22, "Glass is slow.")], mode="a")
        run = self.update()
        self.assertEqual(run["changed"], 1)
        self.assertEqual(self.rows("SELECT exchange, prompt, reply FROM passages WHERE exchange < 3 ORDER BY exchange"),
                         before)
        self.assertEqual(self.rows("SELECT exchange, prompt FROM passages WHERE exchange >= 3 ORDER BY exchange"),
                         [(3, "pasted words about copper"), (4, "and glass?")])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH 'aluminium'"),
                         [(1,)])
        self.assertEqual(self.rows("SELECT active FROM conversations"), [("2026-08-10T09:22:00.000Z",)])
        self.assertTrue(path.exists())

    def test_a_rewritten_transcript_is_read_from_scratch(self):
        self.write(SID, KETTLE)
        self.update()
        self.write(SID, [typed(1, "only this now"), said(2, "Fine.")])
        self.update()
        self.assertEqual(self.rows("SELECT prompt FROM passages"), [("only this now",)])
        self.assertEqual(archive.search("kettle", path=self.db), [])

    def test_a_rewrite_of_the_same_size_is_read_from_scratch(self):
        path = self.write(SID, KETTLE)
        self.update()
        size = path.stat().st_size
        # Every "kettle" becomes "kittle": the same bytes in number, different
        # words, and the old ones must stop being findable.
        path.write_text(path.read_text().replace("kettle", "kittle"))
        self.assertEqual(path.stat().st_size, size)
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
        self.assertEqual(self.update()["changed"], 1)
        self.assertEqual(archive.search("kettle", path=self.db), [])
        self.assertEqual(len(archive.search("kittle", path=self.db)), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM passages"), [(4,)])

    def test_a_rewrite_that_also_grew_is_read_from_scratch(self):
        path = self.write(SID, KETTLE)
        self.update()
        self.write(SID, [typed(1, "a different start entirely"), said(2, "Yes.")] + KETTLE[2:]
                   + [said(30, "More than before.")])
        self.assertGreater(path.stat().st_size, 0)
        self.update()
        self.assertEqual(self.rows("SELECT prompt FROM passages WHERE exchange=0"),
                         [("a different start entirely",)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM passages WHERE prompt='Why does the kettle whistle?'"),
                         [(1,)])

    def test_a_rewrite_deep_inside_a_growing_file_is_read_from_scratch(self):
        # The changed word sits well past the first 4 KB and well before the
        # line reading resumes at, and the file still grows.
        early = [typed(1, "start"), said(2, "padding " * 1000 + "zebra"), typed(3, "next")]
        path = self.write(SID, early + KETTLE[2:])
        self.update()
        text = path.read_text()
        self.assertGreater(text.index("zebra"), 4096)
        path.write_text(text.replace("zebra", "zebru"))
        self.write(SID, [said(40, "And one more thing.")], mode="a")
        self.update()
        self.assertEqual(archive.search("zebra", path=self.db), [])
        self.assertEqual(len(archive.search("zebru", path=self.db)), 1)

    def test_a_small_file_that_grows_is_appended_to_not_rebuilt(self):
        path = self.write(SID, [typed(1, "tiny"), said(2, "Tiny answer."), typed(3, "again")])
        self.assertLess(path.stat().st_size, 4096)
        self.update()
        tail = self.rows("SELECT tail FROM conversations")[0][0]
        self.assertGreater(tail, 0)
        self.write(SID, [said(4, "Again, then."), typed(5, "and once more")], mode="a")
        with mock.patch.object(archive, "read_lines", wraps=archive.read_lines) as read:
            self.update()
        self.assertEqual([c.args[1] for c in read.call_args_list], [tail])
        self.assertEqual(self.rows("SELECT exchange, prompt FROM passages ORDER BY exchange"),
                         [(0, "tiny"), (1, "again"), (2, "and once more")])

    def test_a_transcript_that_is_gone_leaves_the_index(self):
        path = self.write(SID, KETTLE)
        self.write(OTHER, [typed(1, "unrelated", sid=OTHER)])
        self.update()
        path.unlink()
        self.update()
        self.assertEqual(self.rows("SELECT id FROM conversations"), [(OTHER,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM passages WHERE conversation=?", SID), [(0,)])

    def test_the_title_is_the_closed_lists_title(self):
        self.write(SID, KETTLE)
        self.update()
        self.assertEqual(self.rows("SELECT title FROM conversations"), [("Kettle physics",)])


class Naming(Home, unittest.TestCase):
    def test_a_peer_file_names_the_conversation(self):
        self.write(SID, KETTLE)
        (self.root / "sessions").mkdir()
        (self.root / "sessions" / "123.json").write_text(json.dumps(
            {"pid": 123, "sessionId": SID, "name": "Cleo", "updatedAt": 5}))
        self.update()
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Cleo",)])

    def test_a_rename_while_the_transcript_is_idle_is_caught(self):
        self.write(SID, KETTLE)
        peer = self.root / "sessions" / "123.json"
        peer.parent.mkdir()
        peer.write_text(json.dumps({"pid": 123, "sessionId": SID, "name": "Cleo", "updatedAt": 5}))
        self.update()
        peer.write_text(json.dumps({"pid": 123, "sessionId": SID, "name": "Tobias", "updatedAt": 6}))
        self.assertEqual(self.update()["changed"], 0)
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Tobias",)])
        # And it outlives the peer file.
        peer.unlink()
        self.update()
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Tobias",)])

    def test_a_rename_only_the_log_saw_is_caught_while_idle(self):
        self.write(SID, KETTLE)
        peer = self.root / "sessions" / "123.json"
        peer.parent.mkdir()
        peer.write_text(json.dumps({"pid": 123, "sessionId": SID, "name": "Cleo", "updatedAt": 5}))
        self.update()
        peer.unlink()
        self.logs[0].write_text(json.dumps({"kind": "flag", "sessionId": f"claude:{SID}",
                                            "name": "Tobias"}) + "\n")
        self.assertEqual(self.update()["changed"], 0)
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Tobias",)])
        # Nobody knows it any more: the stored name stands.
        self.logs[0].unlink()
        self.update()
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Tobias",)])

    def test_after_the_peer_file_the_log_remembers_the_name(self):
        self.write(SID, KETTLE)
        self.logs[0].write_text("\n".join(json.dumps(r) for r in (
            {"kind": "flag", "sessionId": f"claude:{SID}", "name": "Cleo"},
            {"kind": "session.seen", "sessionId": SID, "name": "Tobias"})) + "\n")
        self.update()
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("Tobias",)])

    def test_with_nothing_to_go_on_the_transcripts_own_name_stands(self):
        self.write(SID, KETTLE + [{"type": "agent-name", "agentName": "kettle-work", "sessionId": SID}])
        self.update()
        self.assertEqual(self.rows("SELECT name FROM conversations"), [("kettle-work",)])


class Searching(Home, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write(SID, KETTLE)
        # A second conversation that mentions copper once, in passing, and
        # a third where it is the whole question.
        self.write(OTHER, [typed(1, "tidy the garden", sid=OTHER),
                           said(2, "Done. The copper tap still drips.", sid=OTHER)])
        third = "00000000-0000-4000-8000-00000000000c"
        self.write(third, [typed(1, "copper copper copper pipes", sid=third),
                           said(2, "Copper pipes, yes.", sid=third)])
        self.update()

    def test_one_row_per_conversation_best_passage_first(self):
        hits = archive.search("copper", path=self.db)
        self.assertEqual(len(hits), 3)
        self.assertEqual(len({h["id"] for h in hits}), 3)
        self.assertEqual(hits[0]["passage"]["prompt"],
                         "\x02copper\x03 \x02copper\x03 \x02copper\x03 pipes")

    def test_one_conversation_with_many_hits_cannot_crowd_out_the_rest(self):
        loud = "00000000-0000-4000-8000-00000000000d"
        records = []
        for i in range(2100):
            records += [typed(2 * i, "copper copper copper copper", sid=loud),
                        said(2 * i + 1, "Copper, copper.", sid=loud)]
        self.write(loud, records)
        self.update()
        ids = [h["id"] for h in archive.search("copper", path=self.db)]
        self.assertEqual(ids[0], loud)
        self.assertIn(OTHER, ids)
        self.assertEqual(len(ids), 4)

    def test_a_row_says_what_the_conversation_is(self):
        hit = archive.search("whistle", path=self.db, live={SID})[0]
        self.assertEqual((hit["id"], hit["title"], hit["cwd"], hit["active"], hit["live"]),
                         (SID, "Kettle physics", "/home/alice/Projects/maple",
                          "2026-08-10T09:16:00.000Z", True))
        self.assertEqual(hit["passage"]["exchange"], 0)
        self.assertIn("\x02whistle\x03", hit["passage"]["prompt"])
        self.assertIn("\x02whistle\x03", hit["passage"]["reply"])

    def test_every_word_must_match_and_the_last_may_be_half_typed(self):
        self.assertEqual([h["id"] for h in archive.search("copper tap dri", path=self.db)], [OTHER])
        self.assertEqual(archive.search("copper whistle", path=self.db), [])

    def test_a_quoted_phrase_stays_a_phrase(self):
        self.assertEqual([h["id"] for h in archive.search('"tap still"', path=self.db)], [OTHER])
        self.assertEqual(archive.search('"still tap"', path=self.db), [])

    def test_nothing_you_type_is_a_syntax_error(self):
        for words in ('co"pper', "AND OR NOT", "(", "-x", "*", "NEAR(a b)", "a:b", '"', "^x"):
            archive.search(words, path=self.db)       # raises if the query is malformed

    def test_short_words_are_not_prefixes(self):
        self.assertEqual(archive.fts_query("do"), '"do"')
        self.assertEqual(archive.fts_query("dri"), '"dri"*')
        self.assertEqual(archive.fts_query('say "it again"'), '"say" "it again"')

    def test_no_index_is_not_an_empty_result(self):
        self.assertIsNone(archive.search("copper", path=self.root / "missing.db"))


class Endpoint(Home, unittest.TestCase):
    """The route the page calls, over HTTP, against a throwaway ~/.claude."""

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
        url = f"http://127.0.0.1:{self.httpd.server_port}/api/search?q={query}"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)

    def test_search_answers_with_rows_and_the_state_of_the_index(self):
        got = self.get("kettle%20whistle")
        self.assertEqual(got["query"], "kettle whistle")
        self.assertEqual([h["id"] for h in got["results"]], [SID])
        self.assertEqual(got["results"][0]["project"], "maple")
        self.assertEqual(got["index"]["conversations"], 1)

    def test_before_the_first_run_there_is_no_index(self):
        self.db.unlink()
        got = self.get("kettle")
        self.assertEqual((got["results"], got["index"]), ([], None))


if __name__ == "__main__":
    unittest.main()
