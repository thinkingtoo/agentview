import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


def block(project, busy=0, updated=0, orphan=False):
    return {"project": project, "busy": busy, "updatedAt": updated, "orphan": orphan}


class Order(unittest.TestCase):
    def test_without_pins_the_liveliest_project_leads(self):
        got = fleet.order_blocks(
            [block("maple", busy=0, updated=50), block("harbor", busy=1, updated=10)], [])
        self.assertEqual([b["project"] for b in got], ["harbor", "maple"])

    def test_pinned_projects_hold_their_place_however_quiet(self):
        # The point of a pin: muscle memory beats freshness for the few
        # projects you look at every day.
        got = fleet.order_blocks(
            [block("maple", busy=1, updated=99), block("harbor"), block("atlas")],
            ["harbor", "atlas"])
        self.assertEqual([b["project"] for b in got], ["harbor", "atlas", "maple"])

    def test_a_pin_naming_a_project_that_is_not_running_is_ignored(self):
        got = fleet.order_blocks([block("maple")], ["harbor", "maple"])
        self.assertEqual([b["project"] for b in got], ["maple"])

    def test_no_project_stays_at_the_bottom_even_if_busy(self):
        got = fleet.order_blocks(
            [block("", busy=3, updated=99, orphan=True), block("maple")], [])
        self.assertEqual([b["orphan"] for b in got], [False, True])


class Overrides(unittest.TestCase):
    def test_a_renamed_project_keeps_its_real_key(self):
        # The label you read changes; the key pins and config are stored
        # against does not, or every rename would orphan its own pin.
        b = fleet.apply_overrides(
            {"project": "harbor", "members": []},
            names={"harbor": "Harbor Co"}, lines={})
        self.assertEqual(b["label"], "Harbor Co")
        self.assertEqual(b["project"], "harbor")

    def test_an_overridden_line_replaces_the_generated_title(self):
        b = fleet.apply_overrides(
            {"project": "harbor",
             "members": [{"sessionId": "abc", "title": "AI answers vs SEO ranking"}]},
            names={}, lines={"abc": "sta rifacendo la home"})
        m = b["members"][0]
        self.assertEqual(m["title"], "sta rifacendo la home")
        self.assertTrue(m["overridden"])

    def test_a_session_with_no_override_is_untouched(self):
        b = fleet.apply_overrides(
            {"project": "maple", "members": [{"sessionId": "xyz", "title": "Call with Sam"}]},
            names={}, lines={"abc": "altro"})
        self.assertEqual(b["members"][0]["title"], "Call with Sam")
        self.assertFalse(b["members"][0]["overridden"])
