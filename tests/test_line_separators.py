"""A record that holds a Unicode line separator is still one record.

JSON Lines cuts a file at "\\n" and nowhere else. `str.splitlines()` also cuts
at U+2028, U+2029 and U+0085, and Claude Code writes those raw inside a JSON
string. A reader that cut there threw the record away: its title, its prompt,
what the session said, the tool call it made, and its write in the strip.

Every record here is invented, and its text holds one separator. The seams are
the ones the page reads through: `claude.scan_cached` and `claude.scan_session`
(the one-pass read of a file, and the incremental read cut at every record
boundary and inside the record), `CodexProvider.live` on a rollout, and the
Stop hook's `last_said`.
"""
import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "hooks"))
import fleet
import stop_line
import test_codex
import test_columns
import test_stuck_kinds_reader
from providers import base, claude

SEPARATORS = (("U+2028", "\u2028"), ("U+2029", "\u2029"), ("U+0085", "\u0085"))
NOW = datetime.datetime(2026, 10, 19, 12, 1, 0, tzinfo=datetime.timezone.utc).timestamp()


def stamp(second):
    return f"2026-10-19T12:00:{second:02d}.000Z"


def lines_of(recs):
    """The records as Claude Code writes them: one line each, non-ASCII left
    as it is. `json.dumps` escapes a separator by default, which would make
    the fixture something the reader never had trouble with."""
    return [json.dumps(r, ensure_ascii=False) + "\n" for r in recs]


def put(path, text, mode="wb"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode) as fh:
        fh.write(text.encode("utf-8"))


def claude_records(sep):
    return [
        {"type": "ai-title", "aiTitle": f"Title{sep}one"},
        {"type": "last-prompt", "lastPrompt": f"Prompt{sep}one"},
        {"type": "user", "timestamp": stamp(1), "message": {"content": f"typed{sep}prompt"}},
        {"type": "assistant", "timestamp": stamp(2), "message": {
            "id": "m1", "content": [{"type": "text", "text": f"Said{sep}this"}]}},
        {"type": "assistant", "timestamp": stamp(3), "message": {
            "id": "m2", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                     "input": {"command": f"echo a{sep}b"}}]}},
    ]


def facts(view):
    """What the page takes from a transcript, in a shape two reads compare."""
    return {"title": view["title"], "prompt": view["prompt"], "said": view["said"],
            "calls": [name for name, _ in view["calls"]],
            "tool": bool(view["lastTool"]), "pending": view["pending"] is not None,
            "writes": sum(w or 0 for w in view["writes"])}


def expected(sep):
    return {"title": f"Title{sep}one", "prompt": f"Prompt{sep}one", "said": f"Said{sep}this",
            "calls": ["Bash"], "tool": True, "pending": True, "writes": 3}


class Reader(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "proj" / "sid.jsonl"
        claude._cache.clear()
        claude.SUBS.cache.clear()
        claude._teams.clear()

    def scan(self):
        return claude.scan_cached(self.path, NOW)

    def raw_text(self):
        return self.path.read_bytes().decode("utf-8")


class OnePass(Reader):
    def test_every_record_is_read_whole(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                claude._cache.clear()
                put(self.path, "".join(lines_of(claude_records(sep))))
                self.assertIn(sep, self.raw_text())
                self.assertEqual(facts(self.scan()), expected(sep))

    def test_a_title_set_early_in_a_big_file_is_found_by_the_cold_read(self):
        # The tail of a big file cannot say what it was called; `_cold` reads
        # the head once, and cuts it into records the same way.
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                claude._cache.clear()
                pad = [{"type": "user", "timestamp": stamp(1), "pad": "p" * 200,
                        "message": {"content": "x"}} for _ in range(30)]
                put(self.path, "".join(lines_of([{"type": "ai-title", "aiTitle": f"Title{sep}one"}] + pad)))
                with mock.patch.object(base, "COLD_BYTES", 2000):
                    self.assertLess(2000, self.path.stat().st_size)
                    self.assertEqual(self.scan()["title"], f"Title{sep}one")


class Incremental(Reader):
    """The same transcript read as it grows. The reader keeps what it knows
    between polls, so a cut at any point must give what one pass gives."""

    def read_cut_at(self, text, at):
        claude._cache.clear()
        put(self.path, text[:at])
        self.scan()
        put(self.path, text[at:], "ab")
        return self.scan()

    def test_cut_at_every_record_boundary_gives_what_one_pass_gives(self):
        for name, sep in SEPARATORS:
            lines = lines_of(claude_records(sep))
            text = "".join(lines)
            for count in range(1, len(lines)):
                with self.subTest(sep=name, records_before_the_cut=count):
                    got = self.read_cut_at(text, len("".join(lines[:count])))
                    self.assertEqual(facts(got), expected(sep))

    def test_cut_just_after_the_separator_inside_a_record_gives_the_same(self):
        # A poll that lands while the record is half written leaves the half
        # for the next one. The half ends on the separator itself.
        for name, sep in SEPARATORS:
            lines = lines_of(claude_records(sep))
            text = "".join(lines)
            for count, line in enumerate(lines):
                with self.subTest(sep=name, record=count):
                    at = len("".join(lines[:count])) + line.index(sep) + 1
                    got = self.read_cut_at(text, at)
                    self.assertEqual(facts(got), expected(sep))

    def test_a_record_appended_after_a_poll_is_read_whole(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                claude._cache.clear()
                lines = lines_of(claude_records(sep))
                put(self.path, "")
                for line in lines:
                    put(self.path, line, "ab")
                    got = self.scan()
                self.assertEqual(facts(got), expected(sep))


class Subagents(Reader):
    def test_a_subagent_record_with_a_separator_is_one_write(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                claude._cache.clear()
                claude.SUBS.cache.clear()
                put(self.path, "".join(lines_of(claude_records(sep))))
                sub = self.path.with_suffix("") / "subagents" / "agent-a1.jsonl"
                put(sub, "".join(lines_of([
                    {"type": "assistant", "timestamp": stamp(10 + i),
                     "message": {"content": [{"type": "text", "text": f"part{sep}{i}"}]}}
                    for i in range(4)])))
                os.utime(sub, (NOW - 5, NOW - 5))
                got = claude.scan_session(self.path, NOW)
                self.assertEqual(sum(w or 0 for w in got["writes"]), 3 + 4)

    def test_a_subagent_file_cut_at_every_record_boundary_counts_the_same(self):
        for name, sep in SEPARATORS:
            sub = self.path.with_suffix("") / "subagents" / "agent-a1.jsonl"
            lines = lines_of([{"type": "assistant", "timestamp": stamp(10 + i),
                               "message": {"content": [{"type": "text", "text": f"part{sep}{i}"}]}}
                              for i in range(4)])
            for count in range(1, len(lines)):
                with self.subTest(sep=name, records_before_the_cut=count):
                    claude._cache.clear()
                    claude.SUBS.cache.clear()
                    put(self.path, "".join(lines_of(claude_records(sep))))
                    put(sub, "".join(lines[:count]))
                    os.utime(sub, (NOW - 5, NOW - 5))
                    claude.scan_session(self.path, NOW)
                    put(sub, "".join(lines[count:]), "ab")
                    os.utime(sub, (NOW - 5, NOW - 5))
                    got = claude.scan_session(self.path, NOW)
                    self.assertEqual(sum(w or 0 for w in got["writes"]), 3 + 4)


class BossMarker(unittest.TestCase):
    """The marker is a file of the boss's, not a transcript, but it is read the
    same way and the ticket names it: its first line is up to the first "\\n"."""

    def test_the_first_line_runs_to_the_newline_not_to_a_separator(self):
        cfg = Path(tempfile.mkdtemp())
        sid = "11111111-1111-1111-1111-111111111111"
        markers = cfg / "pm" / ".boss-sessions"
        markers.mkdir(parents=True)
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                (markers / sid).write_text(f"lead{sep}engine\nsecond line\n", encoding="utf-8")
                self.assertEqual(claude.boss_marker(sid, cfg), f"lead{sep}engine")


class Codex(unittest.TestCase):
    TID = test_codex.TID

    def rollout(self, sep):
        t = test_codex
        return [t.meta(),
                t.rec(t.T0, "event_msg", type="task_started"),
                t.rec(t.T0, "event_msg", type="user_message", message=f"Prompt{sep}one"),
                t.rec(t.T0, "event_msg", type="agent_message", message=f"Said{sep}this"),
                t.rec("2026-09-22T10:49:56.218Z", "event_msg", type="task_complete")]

    def session(self, provider):
        got = provider.live()
        self.assertEqual([s["id"] for s in got], [self.TID])
        return got[0]

    def fixture(self):
        """A live Codex session over a fake `~/.codex` and `/proc`: the folder and its rollout's path."""
        home = test_codex.Home()
        home.thread()
        home.lock()
        home.holder(4242)
        return home, home.rollout(records=[], mode="a")

    def check(self, session, sep):
        self.assertEqual((session["status"], session["prompt"], session["said"]),
                         ("idle", f"Prompt{sep}one", f"Said{sep}this"))

    def test_every_record_is_read_whole(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                home, path = self.fixture()
                put(path, "".join(lines_of(self.rollout(sep))))
                self.assertIn(sep, path.read_bytes().decode("utf-8"))
                self.check(self.session(home.provider()), sep)

    def test_cut_at_every_record_boundary_and_after_the_separator_gives_the_same(self):
        for name, sep in SEPARATORS:
            lines = lines_of(self.rollout(sep))
            text = "".join(lines)
            cuts = [("boundary", count, len("".join(lines[:count]))) for count in range(1, len(lines))]
            cuts += [("inside", count, len("".join(lines[:count])) + line.index(sep) + 1)
                     for count, line in enumerate(lines) if sep in line]
            for where, count, at in cuts:
                with self.subTest(sep=name, cut=where, record=count):
                    home, path = self.fixture()
                    provider = home.provider()
                    put(path, text[:at])
                    self.session(provider)
                    put(path, text[at:], "ab")
                    self.check(self.session(provider), sep)


class ThroughTheRoster(test_stuck_kinds_reader.Base):
    """From a transcript file up to the roster the page is drawn from. The words
    a record holds come out whole, separator and all: escaping them is the
    page's job (`ui_smoke.separator_pass`), cutting them is not the reader's."""

    def setUp(self):
        super().setUp()
        test_columns.Base.setUp(self)

    def roster(self, sep, make=fleet.roster):
        claude._cache.clear()
        self.session([], status="idle")
        put(self.transcript, "".join(lines_of(claude_records(sep))))
        path = self.cfg / "sessions" / "100.json"
        peer = json.loads(path.read_text())
        peer["updatedAt"] = peer["statusUpdatedAt"] = int(time.time() * 1000) - 600_000   # stopped, and not read yet
        path.write_text(json.dumps(peer))
        fleet.CONFIG.write_text("{}")
        return make(providers=[self.provider])

    def test_a_record_with_a_separator_in_it_reaches_the_member_and_the_tile(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                member, = self.roster(sep, fleet.members)
                tile, = self.roster(sep)["columns"][0]["sessions"]
                # The title and the prompt arrive whole. What it said is shaped into the
                # card's one sentence, the last line of the words, and the core reads
                # prose by lines: a separator is a line break to it, as `\n` is. What
                # matters here is that the record was read at all; it used to be dropped.
                self.assertEqual((member["title"], member["prompt"], member["said"]),
                                 (f"Title{sep}one", f"Prompt{sep}one", "this"))
                self.assertEqual(tile["handover"], "this")
                self.assertIsNotNone(member["lastTool"])      # the record with the call is there too


class Hook(unittest.TestCase):
    def test_the_newest_thing_said_survives_a_separator_in_it(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                text = "".join(lines_of([
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": f"last{sep}one"}]}}]))
                self.assertEqual(stop_line.last_said(text), f"last{sep}one")

    def test_a_half_line_cut_at_the_start_of_a_tail_is_still_skipped(self):
        for name, sep in SEPARATORS:
            with self.subTest(sep=name):
                whole = lines_of([{"type": "assistant", "message": {"content": [
                    {"type": "text", "text": f"older{sep}words"}]}}])[0]
                half = whole[whole.index(sep) + 1:]
                text = half + "".join(lines_of([
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "whole"}]}}]))
                self.assertEqual(stop_line.last_said(text), "whole")


if __name__ == "__main__":
    unittest.main()
