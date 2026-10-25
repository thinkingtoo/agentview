"""The Round: one poll, as `poll.round` makes it.

Ask every provider, build the roster, settle what is forgotten, sweep the
Pastes, and hand the handler one dict. A provider that fails or stalls is
reported and the round goes on without it; nothing of that provider is
forgotten, and session lines are forgotten only on a round everyone answered.
Everything here is reached through `poll.round` and what the stores say
afterwards; nothing is patched but the config path (and the live budget, to
make a stall short).
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
import poll
import providers
import marks
from providers.base import Provider
from test_providers import Fake, minimal

NOW = 1790000000.0


class Broken(Provider):
    name = "broken"
    capabilities = frozenset()

    def live(self):
        raise RuntimeError("sqlite is locked")


class Back(Broken):
    """The broken provider, answering again with nothing live."""

    def live(self):
        return []


class Slow(Provider):
    name = "slow"
    capabilities = frozenset()
    gate = threading.Event()

    def live(self):
        self.gate.wait(10)
        return []


class Limited(Fake):
    """A provider whose account is at its usage limit, which it says when asked."""
    name = "limited"

    def limit(self):
        return {"name": "Limited", "at": int((NOW - 60) * 1000), "resetsAt": None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # The config path is a module global until there is a config module;
        # the round itself takes everything else as a parameter.
        (self.tmp / "config.json").write_text("{}")
        fleet.CONFIG, was = self.tmp / "config.json", fleet.CONFIG
        self.addCleanup(setattr, fleet, "CONFIG", was)
        self.marks = self.tmp / "marks.json"
        self.lines = self.tmp / "lines"
        self.lines.mkdir()
        self.pastes = self.tmp / "pastes"
        self.pastes.mkdir()

    def round(self, *providers, now=NOW):
        return poll.round(providers=list(providers), now=now, marks_path=self.marks,
                          lines_root=self.lines)


class Answering(Base):
    def test_a_provider_that_raises_does_not_take_the_others_down(self):
        got = self.round(Broken(), Fake([minimal()]))
        self.assertEqual([f["key"] for f in got["flags"]], ["fake:s1"])
        self.assertEqual(got["providers"]["fake"], {"ok": True})
        self.assertFalse(got["providers"]["broken"]["ok"])
        self.assertIn("sqlite is locked", got["providers"]["broken"]["error"])

    def test_a_provider_that_stalls_is_reported_within_the_budget(self):
        slow = Slow()
        fleet.LIVE_BUDGET, was = 0.2, fleet.LIVE_BUDGET
        try:
            t = time.perf_counter()
            got = self.round(slow, Fake([minimal()]))
            self.assertLess(time.perf_counter() - t, 1.5)
        finally:
            fleet.LIVE_BUDGET = was
            slow.gate.set()
        self.assertEqual([f["key"] for f in got["flags"]], ["fake:s1"])
        self.assertFalse(got["providers"]["slow"]["ok"])
        self.assertEqual(got["providers"]["fake"], {"ok": True})

    def test_a_provider_that_returns_nonsense_is_a_failed_provider(self):
        class Odd(Provider):
            name = "odd"

            def live(self):
                return {"not": "a list"}
        got = self.round(Odd())
        self.assertFalse(got["providers"]["odd"]["ok"])

    def test_the_result_is_what_the_page_reads(self):
        got = self.round(Fake([minimal()]))
        self.assertEqual(set(got), {"columns", "counts", "banners", "flags", "pastes", "kept", "providers"})
        self.assertEqual(got["columns"][0]["sessions"][0]["key"], "fake:s1")


class Forgetting(Base):
    def setUp(self):
        super().setUp()
        for key in ("fake:s1", "fake:gone", "broken:z"):
            marks.mark(key, 100, True, self.marks)
        marks.pin("broken:z", True, self.marks)
        marks.pin("fake:gone", True, self.marks)
        lines.write("gone", did="old words", root=self.lines)

    def test_a_failed_providers_marks_and_pins_survive_the_round(self):
        self.round(Broken(), Fake([minimal()]))
        self.assertEqual(marks.load(self.marks), {"fake:s1": {"seen": 100, "read": 100},
                                                  "broken:z": {"seen": 100, "read": 100, "pinned": True}})

    def test_lines_are_kept_while_any_provider_is_missing(self):
        self.round(Broken(), Fake([minimal()]))
        self.assertEqual(lines.read("gone", self.lines).get("did"), "old words")

    def test_a_sessions_own_line_is_read_from_the_lines_root_given(self):
        lines.write("s1", did="halfway through the import", root=self.lines)
        tile = self.round(Fake([minimal()]))["columns"][0]["sessions"][0]
        # The tile carries the did in what the filter box searches.
        self.assertIn("halfway through the import", tile["find"])

    def test_lines_of_gone_sessions_go_on_a_round_everyone_answered(self):
        self.round(Fake([minimal()]))
        self.assertEqual(lines.read("gone", self.lines), {})
        # The gone session of the provider that answered is forgotten; a
        # provider not asked this round keeps its marks.
        self.assertEqual(marks.load(self.marks), {"fake:s1": {"seen": 100, "read": 100},
                                                  "broken:z": {"seen": 100, "read": 100, "pinned": True}})

    def test_lines_are_kept_while_a_provider_is_broken_since_start_up(self):
        # A provider whose module did not load never answers either, and its
        # sessions write line files all the same (ADR-0001).
        providers._broken["providers.gone"] = "ImportError: no module named gone"
        self.addCleanup(providers._broken.pop, "providers.gone")
        got = self.round(Fake([minimal()]))
        self.assertEqual(lines.read("gone", self.lines).get("did"), "old words")
        self.assertFalse(got["providers"]["providers.gone"]["ok"])

    def test_a_provider_back_with_nothing_live_loses_its_gone_sessions(self):
        # The round that missed `broken` kept its marks and every line (the
        # tests above); once it answers with nothing live, its session is gone
        # from every store, and on this full round so is the gone line file.
        lines.write("s1", did="still here", root=self.lines)
        self.round(Broken(), Fake([minimal()]))
        self.round(Back(), Fake([minimal()]))
        self.assertEqual(marks.load(self.marks), {"fake:s1": {"seen": 100, "read": 100}})
        self.assertEqual(lines.read("gone", self.lines), {})
        self.assertEqual(lines.read("s1", self.lines).get("did"), "still here")


class Sweeping(Base):
    def test_an_orphan_paste_text_is_swept_by_the_round(self):
        orphan = self.pastes / "deadbeef.txt"
        orphan.write_text("a text whose record never came")
        old = NOW - 3600
        os.utime(orphan, (old, old))
        self.round(Fake([minimal()]))
        self.assertFalse(orphan.exists())


class Banners(Base):
    def test_the_limit_of_a_provider_that_answered_is_a_banner(self):
        got = self.round(Limited([minimal()]))
        self.assertEqual([b["kind"] for b in got["banners"]], ["limit"])

    def test_the_limit_of_a_provider_that_did_not_answer_is_not_news(self):
        class Gone(Limited):
            def live(self):
                raise RuntimeError("down")
        got = self.round(Gone([minimal()]), Fake([minimal()]))
        self.assertEqual(got["banners"], [])


if __name__ == "__main__":
    unittest.main()
