"""What the header and the banners say: how many sessions need the person, how
many others are stuck, how many are moving, and the page-wide conditions.

Through `roster()` with fake providers, the way the columns are tested. The
page counts nothing and decides nothing: it prints `counts`, lights up the
tiles whose `counted` names the count that was clicked, and prints `banners`.
Names and texts are invented.
"""
import collections
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_columns import Base, session
from test_needs_you import asks, waiting
from test_stuck_kinds import failure, hung


def moving(sid="a", project="maple", **over):
    """Busy, and written to a moment ago."""
    return session(sid, project, status="busy", quietFor=0.1, **over)


def idle(sid="a", project="maple", **over):
    return session(sid, project, status="idle", **over)


class Counts(Base):
    def counts(self, *sessions, **kw):
        return self.roster(*sessions, **kw)["counts"]

    def test_the_header_counts_what_needs_you_what_else_is_stuck_and_what_is_moving(self):
        got = self.counts(
            waiting("n1", asking=asks()), waiting("n2", asking=asks()),
            hung("h1", quiet=14.0),
            idle("l1", failure=failure("limit")),
            idle("e1", failure=failure("error")),
            moving("m1"), moving("m2"), moving("m3"),
            idle("i1"))
        self.assertEqual(got, {"needs": 2, "otherStuck": 3, "moving": 3})

    def test_a_roster_with_no_sessions_counts_nothing(self):
        self.assertEqual(self.counts(), {"needs": 0, "otherStuck": 0, "moving": 0})

    def test_a_session_that_needs_you_while_a_job_runs_is_counted_once_as_needing_you(self):
        got = self.counts(waiting("a", asking=asks(), bgTasks=[{"label": "watch", "since": 3.0}]))
        self.assertEqual(got, {"needs": 1, "otherStuck": 0, "moving": 0})

    def test_a_session_waiting_on_a_background_job_is_moving_not_idle(self):
        got = self.counts(idle("a", bgTasks=[{"label": "watch", "since": 3.0}]), idle("b"))
        self.assertEqual(got, {"needs": 0, "otherStuck": 0, "moving": 1})

    def test_the_counts_cover_every_project_and_no_project(self):
        got = self.counts(waiting("a", project="maple", asking=asks()), moving("b", "orchard"),
                          moving("c", None), hung("d", project="orchard", quiet=14.0))
        self.assertEqual(got, {"needs": 1, "otherStuck": 1, "moving": 2})

    def test_a_routine_is_in_no_count(self):
        got = self.counts(moving("a"), moving("r", None, routine="nightly-report"),
                          waiting("w", project=None, routine="weekly-digest", asking=asks()))
        self.assertEqual(got, {"needs": 0, "otherStuck": 0, "moving": 1})


class Counted(Base):
    """Each tile says which count it is in, so that the page lights up the
    tiles of the count that was clicked without knowing what any kind means."""

    def counted(self, *sessions):
        tiles = self.roster(*sessions)["columns"][0]["sessions"]
        return {t["name"]: t["counted"] for t in tiles}

    def test_a_tile_names_the_count_it_is_in(self):
        got = self.counted(
            waiting("n", name="Vera", asking=asks()),
            hung("h", name="Mei", quiet=14.0),
            idle("l", name="Odile", failure=failure("limit")),
            idle("e", name="Saskia", failure=failure("error")),
            moving("m", name="Kasper"),
            idle("i", name="Femi"))
        self.assertEqual(got, {"Vera": "needs", "Mei": "otherStuck", "Odile": "otherStuck",
                               "Saskia": "otherStuck", "Kasper": "moving", "Femi": None})

    def test_the_counts_are_the_tiles_that_name_them(self):
        got = self.roster(waiting("n", asking=asks()), hung("h", quiet=14.0),
                          moving("m1"), moving("m2"), idle("i"))
        named = collections.Counter(t["counted"] for c in got["columns"] for t in c["sessions"])
        self.assertEqual(got["counts"], {k: named[k] for k in ("needs", "otherStuck", "moving")})


MB = 1024 * 1024
Usage = collections.namedtuple("usage", "total used free")


class Banners(Base):
    """A condition of the whole machine is one banner across the page, said by
    the roster and by nothing else; no tile carries it."""

    def setUp(self):
        super().setUp()
        # The folder Claude Code writes to, which is the disk that counts. A
        # folder of our own, so that the machine's real one is never asked.
        self.claude = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.claude, True)
        os.environ["CLAUDE_CONFIG_DIR"], was = str(self.claude), os.environ.get("CLAUDE_CONFIG_DIR")
        self.addCleanup(lambda: os.environ.pop("CLAUDE_CONFIG_DIR") if was is None
                        else os.environ.__setitem__("CLAUDE_CONFIG_DIR", was))

    def disk(self, free_mb, elsewhere_mb=80_000, total_mb=400_000):
        """The disk the sessions write to has this much left; any other disk
        has `elsewhere_mb`. An exception stands for a disk that cannot be read."""
        def usage(path):
            if isinstance(free_mb, Exception):
                raise free_mb
            left = free_mb if Path(path) == self.claude else elsewhere_mb
            return Usage(total_mb * MB, (total_mb - left) * MB, left * MB)
        was = fleet.disk_usage
        fleet.disk_usage = usage
        self.addCleanup(setattr, fleet, "disk_usage", was)

    def banners(self, *sessions):
        return self.roster(*sessions)["banners"]

    def test_a_disk_with_room_has_no_banner(self):
        self.disk(80_000)
        self.assertEqual(self.banners(moving("a")), [])

    def test_a_full_disk_is_one_banner_that_says_how_much_is_left(self):
        self.disk(212)
        self.assertEqual(self.banners(moving("a"), moving("b")),
                         [{"kind": "disk", "text": "Disk full: 212 MB left where sessions write"}])

    def test_a_disk_with_nothing_left_says_so(self):
        self.disk(0)
        self.assertEqual(self.banners()[0]["text"], "Disk full: 0 MB left where sessions write")

    def test_the_banner_is_the_roster_s_and_not_a_tile_s(self):
        self.disk(212)
        got = self.roster(moving("a", name="Kasper"), idle("b", name="Femi"))
        self.assertEqual({t["name"]: (t["stuck"], t["counted"]) for t in got["columns"][0]["sessions"]},
                         {"Kasper": (None, "moving"), "Femi": (None, None)})
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 0, "moving": 1})

    def test_full_is_less_than_five_hundred_megabytes_unless_the_config_says_otherwise(self):
        self.disk(499)
        self.assertEqual(len(self.banners()), 1)
        self.disk(500)
        self.assertEqual(self.banners(), [])
        self.config = {"disk_full_mb": 2048}
        self.disk(1536)
        self.assertEqual(self.banners()[0]["text"], "Disk full: 1.5 GB left where sessions write")
        self.disk(2048)
        self.assertEqual(self.banners(), [])

    def test_a_threshold_that_is_not_a_number_of_megabytes_is_five_hundred(self):
        self.disk(300)
        for bad in (0, -5, "lots", None, True, [1]):
            with self.subTest(bad=bad):
                self.config = {"disk_full_mb": bad}
                self.assertEqual(len(self.banners()), 1)

    def test_it_is_the_disk_the_sessions_write_to_that_counts_and_no_other(self):
        self.disk(80_000, elsewhere_mb=10)
        self.assertEqual(self.banners(), [])
        self.disk(212, elsewhere_mb=80_000)
        self.assertEqual(len(self.banners()), 1)

    def test_a_disk_that_cannot_be_read_is_no_banner_and_no_crash(self):
        self.disk(OSError("no such file"))
        self.assertEqual(self.banners(moving("a")), [])


if __name__ == "__main__":
    unittest.main()
