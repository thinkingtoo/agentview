"""The roster's `columns`: what the overview page draws, one per project.

The page reads `columns` and decides nothing of its own -- no grouping, no
ordering -- so everything it shows is checked here, through `roster()` with a
fake provider, the way `test_providers` and `test_round` reach the core.
Names and texts are invented.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
import marks
from test_providers import Fake, minimal


def session(sid, project="maple", **over):
    """A live session working in `/home/alice/Projects/<project>`."""
    cwd = f"/home/alice/Projects/{project}" if project else ""
    return minimal(id=sid, cwd=cwd, **over)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.config = {}
        fleet.CONFIG, was = tmp / "config.json", fleet.CONFIG
        self.addCleanup(setattr, fleet, "CONFIG", was)
        marks.store, kept = (lambda: tmp / "marks.json"), marks.store
        self.addCleanup(setattr, marks, "store", kept)
        self.lines = tmp / "lines"
        lines.store, kept = (lambda: self.lines), lines.store
        self.addCleanup(setattr, lines, "store", kept)
        # No test reaches GitHub or writes the real CI cache (ticket 22): the
        # ones about CI put their own answer here.
        self.addCleanup(setattr, fleet, "CI_STATE", fleet.CI_STATE)
        fleet.CI_STATE = lambda repo, branch: {"status": "unknown"}

    def roster(self, *sessions, provider=None):
        fleet.CONFIG.write_text(json.dumps(self.config))
        return fleet.roster(providers=[provider or Fake(sessions)])

    def members(self, *sessions, provider=None):
        """Every session as the round made it, in the order the overview is made from."""
        fleet.CONFIG.write_text(json.dumps(self.config))
        return fleet.members(providers=[provider or Fake(sessions)])

    READ = ("key", "status", "flag", "blocked", "waitingFor", "n", "ask")

    def heard(self, *sessions):
        """What the chime reads of each session: its row in `flags`, whether
        that rings (the raw flag is waiting or stuck, or it wrote down what
        blocks it), and the fields the flag comes from."""
        rows = self.members(*sessions)
        return [{**f, "rings": f["flag"] in ("waiting", "stuck") or f["blocked"],
                 **{k: m[k] for k in self.READ}}
                for m, f in zip(rows, fleet.flags_of(rows))]

    def tile(self, *sessions, **kw):
        """The first tile of the first column."""
        return self.roster(*sessions, **kw)["columns"][0]["sessions"][0]

    def wrote(self, sid, did):
        """The session has written its own line for the turn it is in."""
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did=did, root=self.lines)


class Columns(Base):
    def test_the_roster_has_a_column_for_each_project_and_no_blocks(self):
        got = self.roster(session("a", "maple"), session("b", "orchard"))
        self.assertNotIn("blocks", got)
        self.assertEqual(sorted(c["name"] for c in got["columns"]), ["Maple", "Orchard"])

    def test_columns_come_pinned_first_with_no_project_last(self):
        self.config = {"pinned": ["orchard", "maple"]}
        got = self.roster(session("a", "maple"), session("b", None),
                          session("c", "orchard"))
        self.assertEqual([c["name"] for c in got["columns"]],
                         ["Orchard", "Maple", "No project"])

    def test_routines_are_in_the_members_for_the_chime_and_not_in_columns(self):
        sessions = (session("a", "maple"), session("r", None, routine="nightly-report"))
        self.assertEqual([m["id"] for m in self.members(*sessions)], ["a", "r"])
        self.assertEqual([c["name"] for c in self.roster(*sessions)["columns"]], ["Maple"])

    def test_a_column_names_its_project_and_keeps_the_raw_name(self):
        got = self.roster(session("a", "maple"))
        self.assertEqual(
            {k: got["columns"][0][k] for k in ("project", "name", "raw", "kind")},
            {"project": "folder:maple", "name": "Maple", "raw": "maple", "kind": "folder"})

    def test_your_own_name_for_a_project_is_the_name_and_the_raw_one_stays(self):
        self.config = {"names": {"maple": "Maple syrup"}}
        column = self.roster(session("a", "maple"))["columns"][0]
        self.assertEqual((column["project"], column["name"], column["raw"]),
                         ("folder:maple", "Maple syrup", "maple"))

    def test_sessions_with_no_project_share_a_column_that_says_so(self):
        column = self.roster(session("a", None))["columns"][0]
        self.assertEqual({k: column[k] for k in ("project", "name", "raw", "kind")},
                         {"project": "", "name": "No project", "raw": "", "kind": "none"})


class Tiles(Base):
    def setUp(self):
        super().setUp()
        # With a line of its own the card does not say the session titles, and
        # a tile's title is not a repeat of it.
        self.config = {"project_lines": {"folder:maple": "Sells maple syrup online"}}

    def test_a_tile_says_who_it_is_what_it_is_on_and_how_to_reach_it(self):
        tile = self.tile(session("a", name="Ilse", status="busy", canJump=True,
                                 title="Checkout form"))
        self.assertEqual(
            {k: tile[k] for k in ("key", "name", "provider", "status", "line", "tags", "jump")},
            {"key": "fake:a", "name": "Ilse", "provider": "fake", "status": "busy",
             "line": "Checkout form", "tags": [], "jump": {"via": "pane"}})

    def test_a_boss_and_a_codex_session_are_tagged(self):
        self.assertEqual(self.tile(session("a", boss=True))["tags"], ["boss"])

        class Codex(Fake):
            name = "codex"
        self.assertEqual(self.tile(provider=Codex([session("b")]))["tags"], ["codex"])

    def test_a_session_with_no_terminal_has_nowhere_to_jump(self):
        self.assertEqual(self.tile(session("a", canJump=False))["jump"],
                         {"via": "none", "reason": "no terminal"})

    def test_what_the_session_wrote_beats_the_title(self):
        self.wrote("a", "Card form wired to the vault, tests green.")
        self.assertEqual(self.tile(session("a", title="Checkout form"))["line"],
                         "Card form wired to the vault, tests green.")

    def test_your_own_line_beats_what_the_session_wrote(self):
        self.wrote("a", "Card form wired to the vault, tests green.")
        self.config["lines"] = {"fake:a": "Saved cards"}
        self.assertEqual(self.tile(session("a", title="Checkout form"))["line"], "Saved cards")

    def test_a_line_that_only_repeats_the_name_is_left_out(self):
        # A `/btw` helper is never named: its title is its name.
        self.assertEqual(self.tile(session("a", name="Handoff review", title="Handoff review"))["line"], "")

    def flag_of(self, **over):
        tile = self.tile(session("a", **over))
        return tile["flag"], tile["flagNote"]

    def test_a_session_asking_a_question_is_waiting_and_says_what_for(self):
        self.assertEqual(self.flag_of(status="waiting", waitingFor="input needed"),
                         ("waiting", "input needed"))

    def test_a_busy_session_gone_quiet_is_hung_on_the_tile_not_a_stuck_flag(self):
        # The chime keeps the `stuck` flag (in `flags`); the tile says Hung and for how long.
        tile = self.tile(session("a", status="busy", quietFor=17.2))
        self.assertEqual((tile["flag"], tile["flagNote"]), (None, ""))
        self.assertEqual((tile["stuck"]["kind"], tile["stuck"]["reason"]), ("hung", "Not moving for 17 min"))

    def test_a_long_tool_call_is_no_flag_on_the_tile_but_a_sign(self):
        # The `tool` flag is replaced by the movement sign ("waiting on: ...,
        # 34 min"); the chime still reads the flag from `flags`.
        tile = self.tile(session("a", status="busy", quietFor=34.0, toolFor=34.0))
        self.assertEqual((tile["flag"], tile["flagNote"]), (None, ""))
        self.assertEqual(tile["movement"]["text"], "waiting on: a command, 34 min")

    def test_a_finished_turn_you_have_not_read_is_ready(self):
        self.assertEqual(self.flag_of(status="idle"), ("ready", ""))

    def test_a_session_at_work_has_no_flag(self):
        self.assertEqual(self.flag_of(status="busy", quietFor=0.1), (None, ""))

    def asked(self, sid, ask, n):
        """The session wrote down what it is blocked on, in the turn it is in."""
        lines.begin_turn(sid, self.lines)
        lines.write(sid, did="working", ask=ask, n=n, root=self.lines)

    def test_a_session_that_wrote_down_what_it_is_blocked_on_says_so_on_its_tile(self):
        # The chime rings for it whatever its flag, so the tile must show why.
        self.asked("a", "Which database should I use?", 1)
        tile = self.tile(session("a", status="idle"))
        self.assertTrue(tile["blocked"])
        self.assertEqual(tile["need"], "Which database should I use?")

    def test_several_questions_are_a_count_not_the_first_of_them(self):
        self.asked("a", "Which database should I use?", 3)
        self.assertEqual(self.tile(session("a", status="idle"))["need"], "3 answers needed")

    def test_a_session_that_wants_nothing_has_no_need_and_is_not_blocked(self):
        tile = self.tile(session("a", status="busy", quietFor=0.1))
        self.assertFalse(tile["blocked"])
        self.assertEqual(tile["need"], "")

    def test_making_the_columns_leaves_the_members_as_they_were(self):
        self.asked("a", "Which database should I use?", 1)
        members = self.members(session("a", "maple"), session("b", None),
                               session("r", None, routine="nightly-report"))
        before = json.dumps(members, sort_keys=True)
        fleet.columns_of(members)
        self.assertEqual(json.dumps(members, sort_keys=True), before)

    def test_the_boss_leads_its_column_whatever_the_activity(self):
        got = self.roster(session("w", name="Mateo", status="busy", updatedAt=1790000900000),
                          session("b", name="Ilse", boss=True, updatedAt=1790000000000))
        self.assertEqual([t["name"] for t in got["columns"][0]["sessions"]], ["Ilse", "Mateo"])

    def test_markup_in_a_name_or_a_line_reaches_the_page_as_the_text_it_is(self):
        # The page prints these as text (tests/ui_smoke.py checks that); the
        # roster must not strip or mangle them on the way.
        hostile = "<img src=x onerror=alert(1)>"
        self.config["names"] = {"maple": hostile}
        column = self.roster(session("a", name=hostile, title="Fix " + hostile))["columns"][0]
        self.assertEqual((column["name"], column["sessions"][0]["name"], column["sessions"][0]["line"]),
                         (hostile, hostile, "Fix " + hostile))

    def test_what_the_filter_box_matches_is_one_lowercase_text_per_tile(self):
        self.wrote("a", "Card form wired")
        tile = self.tile(session("a", name="Ilse", title="Checkout Form", prompt="Fix the Retry logic",
                                 branch="saved-cards"))
        for word in ("ilse", "checkout form", "card form wired", "fix the retry logic",
                     "saved-cards", "/home/alice/projects/maple"):
            self.assertIn(word, tile["find"])


if __name__ == "__main__":
    unittest.main()
