"""The order `members()` lists sessions in, and your own line laid over the
generated one.

The overview's columns have their own order (pins, then kind, then name:
`test_columns`); this is the order of the sessions underneath it, which is
what settles a tie between two sessions that end up in one column.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_columns import Base, session


class Order(Base):
    def ids(self, *sessions):
        return [m["id"] for m in self.members(*sessions)]

    def test_without_pins_the_liveliest_project_leads(self):
        busy = dict(status="busy", quietFor=0.1)
        self.assertEqual(
            self.ids(session("m", "maple", updatedAt=50, **busy),
                     session("h1", "harbor", updatedAt=10, **busy),
                     session("h2", "harbor", updatedAt=10, **busy)),
            ["h1", "h2", "m"])

    def test_a_project_with_a_session_to_read_leads_the_busy_ones(self):
        self.assertEqual(
            self.ids(session("m", "maple", status="busy", quietFor=0.1, updatedAt=99),
                     session("h", "harbor", status="idle", updatedAt=10)),
            ["h", "m"])

    def test_pinned_projects_hold_their_place_however_quiet(self):
        # The point of a pin: muscle memory beats freshness for the few
        # projects you look at every day.
        self.config = {"pinned": ["harbor", "atlas"]}
        self.assertEqual(
            self.ids(session("m", "maple", status="busy", updatedAt=99), session("h", "harbor"),
                     session("a", "atlas")),
            ["h", "a", "m"])

    def test_a_pin_naming_a_project_that_is_not_running_is_ignored(self):
        self.config = {"pinned": ["harbor", "maple"]}
        self.assertEqual(self.ids(session("m", "maple")), ["m"])

    def test_no_project_stays_at_the_bottom_even_if_busy(self):
        self.assertEqual(
            self.ids(session("n", None, status="busy", updatedAt=99), session("m", "maple")),
            ["m", "n"])

    def test_routines_come_after_everything(self):
        self.assertEqual(
            self.ids(session("r", None, routine="nightly-report", status="busy", updatedAt=99),
                     session("n", None), session("m", "maple")),
            ["m", "n", "r"])


class OwnLine(unittest.TestCase):
    def test_an_own_line_replaces_the_generated_title(self):
        m = {"key": "abc", "title": "AI answers vs SEO ranking"}
        fleet.lay_own_line(m, {"abc": "sta rifacendo la home"})
        self.assertEqual((m["title"], m["own"], m["generated"], m["overridden"]),
                         ("sta rifacendo la home", "sta rifacendo la home", "AI answers vs SEO ranking", True))

    def test_a_session_with_no_own_line_is_untouched(self):
        m = {"key": "xyz", "title": "Call with Sam"}
        fleet.lay_own_line(m, {"abc": "altro"})
        self.assertEqual((m["title"], m["own"], m["overridden"]), ("Call with Sam", "", False))

    def test_only_words_are_a_line(self):
        for junk in (7, "", "   ", ["x"], None):
            with self.subTest(junk=junk):
                m = {"key": "abc", "title": "Call with Sam"}
                fleet.lay_own_line(m, {"abc": junk})
                self.assertEqual((m["title"], m["overridden"]), ("Call with Sam", False))


if __name__ == "__main__":
    unittest.main()
