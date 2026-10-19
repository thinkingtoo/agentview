"""Correcting projects by hand: move, rename, merge and pin.

Everything goes through `roster()` with fake providers and a config in a temp
dir, the way `test_projects` does, and the routes through a server on port 0
with its own config. Nothing here reads the real `~/.claude/pm`, the real tmux
or the real `config.json`. Names and texts are invented.
"""
import json
import sys
import tempfile
import threading
import time
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
import seen
import server
from test_providers import Fake, minimal
from test_projects import TrackFixtures, sess

LOOM = "repo:example.com/alice/loom"
ORCHARD = "repo:example.com/alice/orchard"
MAPLE = "repo:example.com/alice/maple"


class Moves(TrackFixtures):
    """`assign` keyed by a track or a repository holds for sessions yet to come."""

    def test_moving_a_repository_into_a_project_places_a_new_session_from_it_there(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {LOOM: "track:checkout"}}
        lead = self.boss("b", orchard, "checkout")
        before = self.claude(lead, sess("a", loom, name="Femi"))
        self.assertEqual(sorted(self.keys(self.column(before, "track:checkout"))),
                         ["claude:a", "claude:b"])
        # A session that starts after the move, in another checkout of the same remote.
        later = self.claude(lead, sess("a", loom, name="Femi"),
                            sess("n", self.repo("loom-two", remote="git@example.com:alice/loom.git"),
                                 name="Odile"))
        self.assertEqual(sorted(self.keys(self.column(later, "track:checkout"))),
                         ["claude:a", "claude:b", "claude:n"])
        self.assertEqual(self.names(later), ["checkout"])

    def test_moving_a_track_takes_every_session_of_the_track_with_it(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"track:docs": LOOM}}
        got = self.claude(self.boss("b", orchard, "docs"),
                          self.worker("w", orchard, "docs", name="Mateo"),
                          sess("a", loom, name="Femi"))
        self.assertEqual(self.names(got), ["loom"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["claude:a", "claude:b", "claude:w"])

    def test_a_move_only_takes_the_sessions_the_project_would_have_had(self):
        # A worker of a track stays in the track when its repository is moved:
        # the track is its project, the repository is only where it works.
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {LOOM: "track:checkout"}}
        got = self.claude(self.boss("b", orchard, "checkout"),
                          self.boss("c", loom, "docs", name="Saskia"),
                          sess("a", loom, name="Femi"))
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:c"])
        self.assertEqual(sorted(self.keys(self.column(got, "track:checkout"))), ["claude:a", "claude:b"])

    def test_a_move_by_plain_name_works_as_it_does_for_a_session(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {LOOM: "orchard"}}
        got = self.claude(sess("a", loom), sess("b", orchard))
        self.assertEqual(self.names(got), ["orchard"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["claude:a", "claude:b"])

    def test_a_project_moved_onto_itself_stays_where_it_is(self):
        loom = self.repo("loom")
        self.config = {"assign": {LOOM: LOOM}}
        self.assertEqual(self.names(self.claude(sess("a", loom))), ["loom"])

    def test_sessions_with_no_project_cannot_be_moved_as_a_whole(self):
        # `""` is not a project, so an empty key is not a way to move them all.
        self.config = {"assign": {"": "track:checkout"}}
        got = self.claude(sess("a", ""))
        self.assertEqual(self.names(got), ["No project"])

    def test_a_single_session_move_ends_with_that_session(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"claude:a": ORCHARD}}
        moved = self.claude(sess("a", loom, name="Femi"), sess("b", orchard, name="Odile"))
        self.assertEqual(sorted(self.keys(self.column(moved, ORCHARD))), ["claude:a", "claude:b"])
        # The session is gone; the next one to start where it started is not
        # carried along, and the entry leaves no column of its own behind.
        after = self.claude(sess("n", loom, name="Ilse"), sess("b", orchard, name="Odile"))
        self.assertEqual(self.keys(self.column(after, LOOM)), ["claude:n"])
        self.assertEqual(self.keys(self.column(after, ORCHARD)), ["claude:b"])

    def test_a_tile_says_it_was_moved_by_hand_and_the_others_do_not(self):
        # The page offers the way back on the tiles you moved and on no other.
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"claude:a": ORCHARD, LOOM: ORCHARD}}
        got = self.claude(sess("a", loom, name="Femi"), sess("b", loom, name="Odile"),
                          sess("c", orchard, name="Ilse"))
        tiles = {t["key"]: t["assigned"] for c in got["columns"] for t in c["sessions"]}
        self.assertEqual(tiles, {"claude:a": True, "claude:b": False, "claude:c": False})

    def test_a_column_lists_the_projects_you_moved_into_it_so_the_page_can_take_them_back(self):
        loom, orchard, pear = self.repo("loom"), self.repo("orchard"), self.repo("pear")
        self.config = {"names": {"repo:example.com/alice/loom": "The loom"},
                       "assign": {LOOM: ORCHARD, "track:docs": ORCHARD, "claude:z": ORCHARD,
                                  "repo:example.com/alice/pear": "orchard"}}
        got = self.claude(sess("a", loom), sess("b", orchard), sess("c", pear))
        self.assertEqual(self.column(got, ORCHARD)["merged"],
                         [{"project": LOOM, "name": "The loom"}, {"project": "track:docs", "name": "docs"}])
        self.assertEqual([c["merged"] for c in got["columns"] if c["project"] != ORCHARD], [])

    def test_the_move_of_one_session_beats_the_move_of_its_repository(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {LOOM: "track:checkout", "claude:a": ORCHARD}}
        got = self.claude(self.boss("b", orchard, "checkout"),
                          sess("a", loom, name="Femi"), sess("c", loom, name="Odile"))
        self.assertEqual(self.keys(self.column(got, ORCHARD)), ["claude:a"])
        self.assertEqual(sorted(self.keys(self.column(got, "track:checkout"))), ["claude:b", "claude:c"])

    def test_a_session_assigned_to_a_project_that_was_moved_follows_it(self):
        # A project you moved away is gone: whatever is put into it, by its
        # identity or by the plain name it had, goes where it went.
        loom, orchard, pear = self.repo("loom"), self.repo("orchard"), self.repo("pear")
        self.config = {"assign": {LOOM: ORCHARD, "claude:a": LOOM, "claude:b": "loom"}}
        got = self.claude(sess("a", pear, name="Femi"), sess("b", pear, name="Odile"),
                          sess("c", loom, name="Ilse"), sess("d", orchard, name="Saskia"))
        self.assertEqual(self.names(got), ["orchard"])
        self.assertEqual(sorted(self.keys(got["columns"][0])),
                         ["claude:a", "claude:b", "claude:c", "claude:d"])

    def lost(self, orchard, **config):
        """A session launched on a shelf (nobody's project) that works in `orchard`."""
        shelf = self.folder("Projects")
        self.config = {"shelves": [str(shelf)], **config}
        return sess("a", shelf, paths=[str(orchard / f"{n}.py") for n in "abc"])

    def test_the_guess_for_a_session_in_no_project_names_where_its_project_was_moved(self):
        # A project merged away is no column any more: the chip must not offer
        # it, and its click must put the session where the chip says.
        orchard, maple = self.repo("orchard"), self.repo("maple")
        for target in (MAPLE, "maple"):             # by identity, and by the plain name
            with self.subTest(target=target):
                got = self.claude(self.lost(orchard, assign={ORCHARD: target}), sess("b", maple))
                self.assertEqual(self.names(got), ["maple", "No project"])
                tile = self.column(got, "")["sessions"][0]
                self.assertEqual(tile["suggestion"], {"project": MAPLE, "name": "maple"})

    def test_the_guess_follows_a_chain_of_moves_and_stops_at_a_cycle(self):
        orchard, maple, pear = self.repo("orchard"), self.repo("maple"), self.repo("pear")
        pear_id = "repo:example.com/alice/pear"
        chain = self.claude(self.lost(orchard, assign={ORCHARD: MAPLE, MAPLE: pear_id}),
                            sess("b", maple), sess("c", pear))
        self.assertEqual(self.column(chain, "")["sessions"][0]["suggestion"],
                         {"project": pear_id, "name": "pear"})
        swap = self.claude(self.lost(orchard, assign={ORCHARD: MAPLE, MAPLE: ORCHARD}),
                           sess("b", maple), sess("c", orchard))
        self.assertEqual(self.column(swap, "")["sessions"][0]["suggestion"],
                         {"project": MAPLE, "name": "maple"})

    def test_a_project_moved_twice_lands_where_the_last_move_leads(self):
        loom, orchard, pear = self.repo("loom"), self.repo("orchard"), self.repo("pear")
        self.config = {"assign": {LOOM: ORCHARD, ORCHARD: "repo:example.com/alice/pear"}}
        got = self.claude(sess("a", loom), sess("b", orchard), sess("c", pear))
        self.assertEqual(self.names(got), ["pear"])
        self.assertEqual(len(got["columns"][0]["sessions"]), 3)

    def test_a_longer_cycle_of_moves_ends_too_and_every_session_has_a_place(self):
        loom, orchard, pear = self.repo("loom"), self.repo("orchard"), self.repo("pear")
        pear_id = "repo:example.com/alice/pear"
        self.config = {"assign": {LOOM: ORCHARD, ORCHARD: pear_id, pear_id: LOOM}}
        got = self.claude(sess("a", loom), sess("b", orchard), sess("c", pear))
        self.assertEqual(self.keys(self.column(got, pear_id)), ["claude:a"])
        self.assertEqual(self.keys(self.column(got, LOOM)), ["claude:b"])
        self.assertEqual(self.keys(self.column(got, ORCHARD)), ["claude:c"])

    def test_two_projects_moved_into_each_other_swap_places_and_do_not_loop(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {LOOM: ORCHARD, ORCHARD: LOOM}}
        got = self.claude(sess("a", loom, name="Femi"), sess("b", orchard, name="Odile"))
        self.assertEqual(self.keys(self.column(got, ORCHARD)), ["claude:a"])
        self.assertEqual(self.keys(self.column(got, LOOM)), ["claude:b"])


class OldConfig(TrackFixtures):
    """R1 and R13: the keys `assign` has always had keep their meaning, and the
    startup migration does not mangle the keys that name a track or a repository."""

    OLD = {"assign": {"abc123": "loom", "claude:def456": "Invoice tool", "codex:ghi789": ORCHARD},
           "lines": {"abc123": "my own words"},
           "pinned": ["loom"], "names": {"loom": "The loom"}}

    def sessions(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        return [sess("abc123", orchard, name="Ilse"), sess("def456", orchard, name="Odile")], loom

    def test_an_old_config_places_its_sessions_as_it_always_did(self):
        (first, second), loom = self.sessions()
        # The server migrates at every start, before the first poll.
        fleet.CONFIG.write_text(json.dumps(self.OLD))
        fleet.migrate_keys()
        self.config = json.loads(fleet.CONFIG.read_text())
        got = self.claude(first, second, sess("x", loom, name="Femi"))
        self.assertEqual(self.names(got), ["The loom", "Invoice tool"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["claude:abc123", "claude:x"])
        self.assertEqual(self.keys(got["columns"][1]), ["claude:def456"])

    def test_the_migration_prefixes_a_bare_session_key_and_nothing_else(self):
        self.config = {**self.OLD, "assign": {
            **self.OLD["assign"], LOOM: "track:checkout", "track:docs": "orchard",
            "client:example.com/alice/loom/acme": "folder:Invoice tool"}}
        fleet.CONFIG.write_text(json.dumps(self.config))
        self.assertEqual(fleet.migrate_keys(), ["assign", "lines"])
        got = json.loads(fleet.CONFIG.read_text())
        self.assertEqual(got["assign"], {
            "claude:abc123": "loom", "claude:def456": "Invoice tool", "codex:ghi789": ORCHARD,
            LOOM: "track:checkout", "track:docs": "orchard",
            "client:example.com/alice/loom/acme": "folder:Invoice tool"})
        self.assertEqual(got["lines"], {"claude:abc123": "my own words"})
        self.assertEqual((got["pinned"], got["names"]), (["loom"], {"loom": "The loom"}))

    def test_the_migration_is_idempotent_with_keys_for_tracks_and_repositories(self):
        self.config = {"assign": {LOOM: "track:checkout", "track:docs": ORCHARD, "claude:a": LOOM}}
        fleet.CONFIG.write_text(json.dumps(self.config))
        self.assertEqual(fleet.migrate_keys(), [])
        self.assertEqual(json.loads(fleet.CONFIG.read_text())["assign"], self.config["assign"])

    def test_a_session_key_is_never_read_as_a_track_or_a_repository(self):
        # Whatever a provider is called, `provider:id` is a session; only the
        # four prefixes projects have name a project.
        loom = self.repo("loom")
        self.config = {"assign": {"claude:loom": "track:checkout", "claude:checkout": ORCHARD}}
        got = self.claude(sess("a", loom, name="Femi"))
        self.assertEqual(self.names(got), ["loom"])


class Served(unittest.TestCase):
    """A server on port 0 with a config of its own, a fake provider behind it
    and every store a throwaway: what the page's clicks reach."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / "config.json"
        self.cfg.write_text("{}")
        self.fake = Fake([minimal(id="a", name="Ilse", cwd="/home/alice/Projects/maple"),
                          minimal(id="b", name="Odile", cwd="/home/alice/Projects/orchard")])
        for target, new in (("fleet.CONFIG", self.cfg),
                            ("fleet._providers", lambda: [self.fake]),
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
        self.serve()

    def serve(self):
        """A server of its own -- also how a restart is made: the same config, a new process."""
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Fleet": "1"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def poll(self):
        with urllib.request.urlopen(self.base + "/api/roster", timeout=20) as r:
            return json.loads(r.read())

    def stored(self):
        return json.loads(self.cfg.read_text())


class Concurrency(Served):
    """R2: the page can send a rename, a move, a pin and a line in the same
    breath, and none of them may undo another."""

    def slow(self):
        """Widen the window between reading the config and replacing it, so a
        write that does not hold the others off loses one every time."""
        real = json.dump

        def slow_dump(*args, **kw):
            time.sleep(0.05)
            return real(*args, **kw)
        patch = mock.patch("json.dump", slow_dump)
        patch.start()
        self.addCleanup(patch.stop)

    def together(self, *calls):
        gate, out = threading.Barrier(len(calls)), []

        def go(path, body):
            gate.wait()
            out.append(self.post(path, body)[0])
        threads = [threading.Thread(target=go, args=call) for call in calls]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        return out

    def test_a_rename_a_move_a_pin_and_a_line_at_once_all_land(self):
        self.slow()
        codes = self.together(
            ("/api/name", {"project": "folder:maple", "label": "Maple tree"}),
            ("/api/assign", {"key": "fake:b", "project": "folder:maple"}),
            ("/api/order", {"pinned": ["folder:orchard"]}),
            ("/api/line", {"key": "fake:a", "text": "in my words"}),
            ("/api/hold", {"hold": True}))
        self.assertEqual(codes, [200] * 5)
        got = self.stored()
        self.assertEqual((got["names"], got["assign"], got["pinned"], got["lines"], got["hold"]),
                         ({"folder:maple": "Maple tree"}, {"fake:b": "folder:maple"},
                          ["folder:orchard"], {"fake:a": "in my words"}, True))

    def test_many_writes_to_one_key_at_once_each_keep_their_own_entry(self):
        self.slow()
        codes = self.together(*[("/api/assign", {"key": f"fake:{n}", "project": f"folder:p{n}"})
                                for n in range(8)])
        self.assertEqual(codes, [200] * 8)
        self.assertEqual(self.stored()["assign"], {f"fake:{n}": f"folder:p{n}" for n in range(8)})

    def test_a_pin_a_swap_a_merge_and_a_rename_at_once_all_land(self):
        self.fake._sessions = [minimal(id=i, name=n, cwd=f"/home/alice/Projects/{w}")
                               for i, n, w in (("a", "Ilse", "maple"), ("b", "Odile", "orchard"),
                                               ("c", "Saskia", "pear"), ("e", "Kasper", "plum"))]
        self.cfg.write_text(json.dumps({"pinned": ["folder:maple", "folder:orchard"]}))
        self.slow()
        codes = self.together(
            ("/api/pin", {"project": "folder:pear", "action": "pin"}),
            ("/api/pin", {"project": "folder:orchard", "action": "swap", "with": "folder:maple"}),
            ("/api/merge", {"source": "folder:plum", "target": "folder:pear"}),
            ("/api/name", {"project": "folder:maple", "label": "Maple tree"}))
        self.assertEqual(codes, [200] * 4)
        got = self.stored()
        self.assertEqual(sorted(got["pinned"]), ["folder:maple", "folder:orchard", "folder:pear"])
        self.assertEqual((got["assign"], got["names"]),
                         ({"folder:plum": "folder:pear"}, {"folder:maple": "Maple tree"}))

    def test_no_write_leaves_a_temp_file_behind(self):
        self.slow()
        self.together(*[("/api/name", {"project": f"folder:p{n}", "label": f"P{n}"}) for n in range(6)])
        self.assertEqual(sorted(p.name for p in self.tmp.glob("config.json*")), ["config.json"])


class Corrected(Served):
    """The page's clicks, one by one, and the roster after each."""

    def setUp(self):
        super().setUp()
        self.fake._sessions = [
            minimal(id=sid, name=name, cwd=f"/home/alice/Projects/{where}")
            for sid, name, where in (("a", "Ilse", "maple"), ("b", "Odile", "orchard"),
                                     ("c", "Saskia", "pear"), ("d", "Femi", "maple"))]

    def columns(self):
        return self.poll()["columns"]

    def names(self):
        return [c["name"] for c in self.columns()]

    def column(self, project):
        return next(c for c in self.columns() if c["project"] == project)

    def keys(self, project):
        return sorted(t["key"] for t in self.column(project)["sessions"])

    def seed(self, **config):
        self.cfg.write_text(json.dumps(config))

    def pin(self, project, action="pin", **body):
        return self.post("/api/pin", {"project": project, "action": action, **body})


class Pins(Corrected):
    def test_pinning_puts_a_project_first_and_pins_keep_the_order_they_were_made_in(self):
        self.assertEqual(self.names(), ["maple", "orchard", "pear"])
        self.assertEqual(self.pin("folder:pear")[0], 200)
        self.assertEqual(self.pin("folder:orchard")[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:pear", "folder:orchard"])
        self.assertEqual(self.names(), ["pear", "orchard", "maple"])
        self.assertEqual([c["pinned"] for c in self.columns()], [True, True, False])

    def test_pinning_twice_pins_once(self):
        self.pin("folder:pear")
        self.pin("folder:pear")
        self.assertEqual(self.stored()["pinned"], ["folder:pear"])

    def test_the_arrow_swaps_a_pinned_project_with_its_neighbour(self):
        self.seed(pinned=["folder:pear", "folder:orchard", "folder:maple"])
        self.assertEqual(self.pin("folder:orchard", "swap", **{"with": "folder:pear"})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:orchard", "folder:pear", "folder:maple"])
        self.assertEqual(self.names(), ["orchard", "pear", "maple"])

    def test_a_swap_over_a_pin_that_has_no_column_still_moves_what_you_can_see(self):
        # The pin of a project nobody is working in is kept, but it takes no
        # place on the page: the arrow must change what you see, not a hidden slot.
        self.seed(pinned=["folder:pear", "folder:gone", "folder:orchard"])
        self.pin("folder:orchard", "swap", **{"with": "folder:pear"})
        self.assertEqual(self.names(), ["orchard", "pear", "maple"])
        self.assertEqual(self.stored()["pinned"], ["folder:orchard", "folder:gone", "folder:pear"])

    def test_pinning_again_unpins_and_the_project_goes_back_among_the_others(self):
        self.seed(pinned=["folder:pear", "folder:orchard"])
        self.assertEqual(self.pin("folder:pear", "unpin")[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:orchard"])
        self.assertEqual(self.names(), ["orchard", "maple", "pear"])
        self.assertFalse(self.column("folder:pear")["pinned"])

    def test_a_pin_written_by_plain_name_counts_as_pinned_and_unpins(self):
        self.seed(pinned=["pear", "orchard"])
        self.assertEqual([c["pinned"] for c in self.columns()], [True, True, False])
        self.pin("folder:pear", "unpin")
        self.assertEqual(self.stored()["pinned"], ["orchard"])

    def test_a_pin_survives_a_restart_of_the_server(self):
        self.pin("folder:pear")
        self.pin("folder:maple")
        self.pin("folder:maple", "swap", **{"with": "folder:pear"})
        self.serve()                         # a new server, the same config file
        self.assertEqual(self.names(), ["maple", "pear", "orchard"])

    def test_no_project_cannot_be_pinned_and_a_malformed_request_is_refused(self):
        for body in ({"project": "", "action": "pin"}, {"project": "folder:pear", "action": "juggle"},
                     {"project": "maple", "action": "pin"}, {"project": 3, "action": "pin"},
                     {"project": "folder:pear", "action": "swap"},
                     {"project": "folder:pear", "action": "swap", "with": "folder:pear"}):
            self.assertEqual(self.post("/api/pin", body)[0], 400, body)
        self.assertEqual(self.stored(), {})

    def test_swapping_with_a_project_that_is_not_pinned_changes_nothing(self):
        self.seed(pinned=["folder:pear"])
        self.pin("folder:pear", "swap", **{"with": "folder:orchard"})
        self.assertEqual(self.stored()["pinned"], ["folder:pear"])


class Renames(Corrected):
    def test_a_rename_is_the_name_on_the_column_and_survives_a_restart(self):
        self.assertEqual(self.post("/api/name", {"project": "folder:maple", "label": "Maple tree"})[0], 200)
        self.serve()
        self.assertEqual(self.names(), ["Maple tree", "orchard", "pear"])
        self.assertEqual(self.column("folder:maple")["raw"], "maple")

    def test_taking_a_rename_back_shows_the_raw_name_even_after_an_older_plain_name_rename(self):
        self.seed(names={"maple": "The old name"})
        self.assertIn("The old name", self.names())
        self.post("/api/name", {"project": "folder:maple", "label": "Maple tree"})
        self.post("/api/name", {"project": "folder:maple", "label": ""})
        self.assertEqual(self.names(), ["maple", "orchard", "pear"])

    def test_renaming_keeps_the_pin_the_line_and_the_moves_of_the_project(self):
        # R10: a rename changes what the column says, nothing it is known by.
        self.seed(pinned=["folder:pear", "folder:orchard"],
                  project_lines={"folder:orchard": "Picking season"},
                  assign={"folder:maple": "folder:orchard", "fake:c": "folder:orchard"})
        before = self.stored()
        self.post("/api/name", {"project": "folder:orchard", "label": "Orchard 2"})
        got = self.stored()
        self.assertEqual({k: v for k, v in got.items() if k != "names"}, before)
        self.assertEqual(got["names"], {"folder:orchard": "Orchard 2"})
        self.assertEqual(self.names(), ["Orchard 2"])
        self.assertEqual(self.keys("folder:orchard"), ["fake:a", "fake:b", "fake:c", "fake:d"])


class Merges(Corrected):
    def test_merging_puts_every_session_of_the_project_into_the_other_and_survives_a_restart(self):
        self.assertEqual(self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})[0], 200)
        self.serve()
        self.assertEqual(self.names(), ["maple", "pear"])
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:b", "fake:d"])
        self.assertEqual(self.stored()["assign"], {"folder:orchard": "folder:maple"})

    def test_a_merge_holds_for_a_session_that_starts_later(self):
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.fake._sessions.append(minimal(id="n", name="Kasper", cwd="/home/alice/Projects/orchard"))
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:b", "fake:d", "fake:n"])

    def test_merging_carries_the_pin_the_line_and_the_moves_that_pointed_at_the_project(self):
        # R10.
        self.seed(pinned=["folder:pear", "folder:orchard"],
                  names={"folder:orchard": "Orchard 2"},
                  project_lines={"folder:orchard": "Picking season"},
                  assign={"folder:pear": "folder:orchard", "fake:a": "folder:orchard", "fake:d": "orchard"})
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        got = self.stored()
        self.assertEqual(got["pinned"], ["folder:pear", "folder:maple"])
        self.assertEqual(got["project_lines"], {"folder:maple": "Picking season"})
        # A project moved into it goes with it; a session you moved there stays
        # as you moved it (it follows the project), so taking the merge back gives it back.
        self.assertEqual(got["assign"], {"folder:orchard": "folder:maple", "folder:pear": "folder:maple",
                                         "fake:a": "folder:orchard", "fake:d": "orchard"})
        self.assertNotIn("folder:orchard", got["names"])
        # What the roster shows: all of it in one pinned column; the plain
        # name that meant the absorbed project goes with it.
        self.assertEqual(self.names(), ["maple"])
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:b", "fake:c", "fake:d"])
        self.assertTrue(self.column("folder:maple")["pinned"])

    def test_no_project_is_left_moved_into_the_absorbed_one_but_its_own_move_and_your_sessions(self):
        self.seed(pinned=["folder:orchard"], names={"folder:orchard": "Orchard 2"},
                  project_lines={"folder:orchard": "Picking season"},
                  assign={"folder:pear": "folder:orchard", "fake:a": "folder:orchard"})
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        got = self.stored()
        pointing = [k for k, v in got["assign"].items() if v == "folder:orchard"]
        self.assertEqual(pointing, ["fake:a"])      # a session you moved: it follows the project
        for field in ("pinned", "names", "project_lines"):
            self.assertNotIn("folder:orchard", got[field], field)

    def test_the_target_keeps_its_own_pin_name_and_line_when_both_had_one(self):
        self.seed(pinned=["folder:orchard", "folder:pear", "folder:maple"],
                  names={"folder:maple": "Maple tree", "folder:orchard": "Orchard 2"},
                  project_lines={"folder:maple": "Syrup", "folder:orchard": "Picking season"})
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        got = self.stored()
        self.assertEqual(got["pinned"], ["folder:pear", "folder:maple"])
        self.assertEqual(got["names"], {"folder:maple": "Maple tree"})
        self.assertEqual(got["project_lines"], {"folder:maple": "Syrup"})

    def test_merging_a_project_into_one_that_was_merged_into_it_turns_the_move_around(self):
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.post("/api/merge", {"source": "folder:maple", "target": "folder:orchard"})
        self.assertEqual(self.stored()["assign"], {"folder:maple": "folder:orchard"})
        self.assertEqual(self.names(), ["orchard", "pear"])
        self.assertEqual(self.keys("folder:orchard"), ["fake:a", "fake:b", "fake:d"])

    def test_the_target_steps_into_the_place_the_source_had_among_the_pins(self):
        self.seed(pinned=["folder:orchard", "folder:pear"])
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "folder:pear"])

    def test_a_source_pinned_twice_leaves_the_target_pinned_once(self):
        self.seed(pinned=["folder:orchard", "folder:pear", "orchard"])
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "folder:pear"])

    def test_a_config_edited_by_hand_into_the_wrong_shapes_does_not_break_a_merge(self):
        # `assign`, `names`, `project_lines` that are not tables, and pins that are not strings
        # (not unhashable ones: the block view's own ordering does not take those).
        for damage in ({"assign": [], "names": 5, "project_lines": None, "pinned": [None, 3, "folder:orchard"]},
                       {"assign": None, "pinned": "folder:orchard"},
                       {"assign": {"fake:z": 7, "folder:pear": ["folder:orchard"]}, "pinned": [7]}):
            self.seed(**damage)
            self.assertEqual(self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})[0], 200)
            got = self.stored()
            self.assertEqual(got["assign"]["folder:orchard"], "folder:maple", damage)
            self.assertNotIn("folder:orchard", got["pinned"], damage)
            self.assertEqual(self.names(), ["maple", "pear"], damage)

    def test_merging_twice_in_a_row_carries_the_first_merge_along(self):
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.post("/api/merge", {"source": "folder:maple", "target": "folder:pear"})
        self.assertEqual(self.stored()["assign"], {"folder:orchard": "folder:pear", "folder:maple": "folder:pear"})
        self.assertEqual(self.names(), ["pear"])

    def test_a_merge_that_names_no_project_or_the_same_one_twice_is_refused(self):
        for body in ({"source": "", "target": "folder:maple"}, {"source": "folder:maple", "target": ""},
                     {"source": "folder:maple", "target": "folder:maple"},
                     {"source": "maple", "target": "folder:pear"}, {"source": 3, "target": "folder:pear"}):
            self.assertEqual(self.post("/api/merge", body)[0], 400, body)
        self.assertEqual(self.stored(), {})


class TakenBack(Corrected):
    def test_a_merge_is_taken_back_by_moving_the_project_into_nothing(self):
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.assertEqual(self.column("folder:maple")["merged"],
                         [{"project": "folder:orchard", "name": "orchard"}])
        self.post("/api/assign", {"key": "folder:orchard", "project": ""})
        self.assertEqual(self.names(), ["maple", "orchard", "pear"])
        self.assertEqual(self.keys("folder:orchard"), ["fake:b"])
        self.assertEqual(self.column("folder:maple")["merged"], [])

    def test_taking_a_merge_back_gives_back_the_sessions_you_had_moved_into_it(self):
        self.post("/api/assign", {"key": "fake:c", "project": "folder:orchard"})
        self.post("/api/merge", {"source": "folder:orchard", "target": "folder:maple"})
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:b", "fake:c", "fake:d"])
        self.post("/api/assign", {"key": "folder:orchard", "project": ""})
        self.assertEqual(self.keys("folder:orchard"), ["fake:b", "fake:c"])
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:d"])
        self.assertEqual(self.stored()["assign"], {"fake:c": "folder:orchard"})


class BlockViewPins(Corrected):
    """The old block view still writes `pinned`, from the names it knows."""

    def test_pinning_in_the_block_view_keeps_the_projects_you_pinned_on_the_overview(self):
        self.seed(pinned=["folder:pear", "folder:orchard"])
        self.assertEqual(self.post("/api/order", {"pinned": ["maple"]})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["maple", "folder:pear", "folder:orchard"])

    def test_the_block_view_still_unpins_what_it_pinned_by_name(self):
        self.seed(pinned=["maple", "folder:pear"])
        self.post("/api/order", {"pinned": []})
        self.assertEqual(self.stored()["pinned"], ["folder:pear"])

    def test_the_overview_keeps_the_place_of_an_identity_the_block_view_names_again(self):
        self.seed(pinned=["folder:pear", "folder:orchard"])
        self.post("/api/order", {"pinned": ["folder:orchard", "maple"]})
        self.assertEqual(self.stored()["pinned"], ["folder:orchard", "maple", "folder:pear"])


class BlockViewUnpins(Corrected):
    """A session moved by hand into a project is a block of its own, named by
    the project's identity, in the old block view -- and that view must be able
    to unpin it, or drag it, like any other."""

    def setUp(self):
        super().setUp()
        self.seed(assign={"fake:c": "folder:maple"}, pinned=["folder:maple", "folder:pear"])

    def pinned_blocks(self):
        return [b["project"] for b in self.poll()["blocks"] if b["pinned"]]

    def test_the_block_view_unpins_a_block_that_is_named_by_an_identity(self):
        self.assertIn("folder:maple", self.pinned_blocks())
        shown = [b["project"] for b in self.poll()["blocks"]]
        self.assertEqual(self.post("/api/order", {"pinned": [], "shown": shown})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:pear"])
        self.assertNotIn("folder:maple", self.pinned_blocks())

    def test_what_the_block_view_did_not_show_stays_pinned_after_its_own_drag(self):
        self.assertEqual(self.post("/api/order", {"pinned": ["folder:maple"], "shown": ["folder:maple", "orchard"]})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "folder:pear"])

    def test_a_list_of_what_it_shows_that_is_not_a_list_of_names_is_refused(self):
        for shown in ("folder:maple", [3], {"a": 1}):
            self.assertEqual(self.post("/api/order", {"pinned": [], "shown": shown})[0], 400, shown)
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "folder:pear"])


class OneNameTwoCards(Corrected):
    """A pin written before projects had identities names a project by its
    plain name, which a track and a folder can share: two cards, one pin. What
    the page shows -- the pinned cards in their order -- says which is which."""

    def setUp(self):
        super().setUp()
        self.seed(pinned=["maple", "folder:orchard"], assign={"fake:c": "track:maple"})
        self.shown = ["track:maple", "folder:maple", "folder:orchard"]

    def order(self):
        return [c["project"] for c in self.columns()]

    def test_the_two_cards_share_the_pin_as_the_page_shows_it(self):
        self.assertEqual(self.order(), self.shown)
        self.assertEqual([c["pinned"] for c in self.columns()], [True, True, True])

    def test_the_arrow_between_them_swaps_them(self):
        self.assertEqual(self.pin("track:maple", "swap", **{"with": "folder:maple", "shown": self.shown})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "track:maple", "folder:orchard"])
        self.assertEqual(self.order(), ["folder:maple", "track:maple", "folder:orchard"])

    def test_unpinning_one_leaves_the_other_pinned(self):
        self.assertEqual(self.pin("folder:maple", "unpin", shown=self.shown)[0], 200)
        self.assertEqual(self.stored()["pinned"], ["track:maple", "folder:orchard"])
        self.assertEqual({c["project"]: c["pinned"] for c in self.columns()},
                         {"track:maple": True, "folder:maple": False, "folder:orchard": True})

    def test_merging_one_into_another_project_leaves_the_other_pinned(self):
        self.assertEqual(self.post("/api/merge", {"source": "folder:maple", "target": "folder:orchard",
                                                  "shown": self.shown})[0], 200)
        self.assertEqual(self.stored()["pinned"], ["track:maple", "folder:orchard"])

    def test_a_click_on_another_card_leaves_the_plain_pin_as_the_block_view_wrote_it(self):
        # One card carries the plain pin: there is nothing to tell apart, and
        # the block view (and a same-named project with no session yet) still
        # needs the plain name.
        self.seed(pinned=["maple"])
        self.assertEqual(self.pin("folder:orchard", shown=["folder:maple"])[0], 200)
        self.assertEqual(self.stored()["pinned"], ["maple", "folder:orchard"])
        self.assertEqual([b["project"] for b in self.poll()["blocks"] if b["pinned"]], ["maple"])

    def test_a_click_on_a_third_card_leaves_two_cards_that_share_a_pin_where_they_are(self):
        self.seed(pinned=["maple", "track:maple"], assign={"fake:c": "track:maple"})
        shown = ["track:maple", "folder:maple"]
        self.assertEqual(self.order(), ["track:maple", "folder:maple", "folder:orchard"])
        self.pin("folder:orchard", shown=shown)
        self.assertEqual(self.stored()["pinned"], ["maple", "track:maple", "folder:orchard"])
        self.assertEqual(self.order(), ["track:maple", "folder:maple", "folder:orchard"])

    def test_the_arrow_swaps_two_cards_that_share_a_pin_when_one_is_also_pinned_by_identity(self):
        # The block view can leave `["maple", "track:maple"]`: the page shows both cards
        # at the place of the first pin.
        self.seed(pinned=["maple", "folder:orchard", "track:maple"], assign={"fake:c": "track:maple"})
        self.assertEqual(self.order(), ["track:maple", "folder:maple", "folder:orchard"])
        self.pin("track:maple", "swap", **{"with": "folder:maple", "shown": self.shown})
        self.assertEqual(self.stored()["pinned"], ["folder:maple", "track:maple", "folder:orchard"])
        self.assertEqual(self.order(), ["folder:maple", "track:maple", "folder:orchard"])

    def test_a_merge_of_one_of_two_cards_that_share_a_pin_puts_the_target_where_the_page_shows_it(self):
        self.seed(pinned=["maple", "folder:orchard", "track:maple"], assign={"fake:c": "track:maple"})
        self.post("/api/merge", {"source": "folder:maple", "target": "folder:orchard", "shown": self.shown})
        self.assertEqual(self.stored()["pinned"], ["track:maple", "folder:orchard"])

    def test_a_pin_that_names_nobody_on_the_page_stays_as_written(self):
        self.seed(pinned=["maple", "gone"], assign={"fake:c": "track:maple"})
        self.pin("folder:maple", "unpin", shown=["track:maple", "folder:maple"])
        self.assertEqual(self.stored()["pinned"], ["track:maple", "gone"])

    def test_without_the_list_the_pin_is_read_as_before(self):
        self.pin("folder:maple", "unpin")
        self.assertEqual(self.stored()["pinned"], ["folder:orchard"])

    def test_a_list_that_is_not_a_list_of_projects_is_refused(self):
        for shown in ("track:maple", [3], {"a": 1}):
            self.assertEqual(self.pin("folder:maple", "unpin", shown=shown)[0], 400, shown)
            self.assertEqual(self.post("/api/merge", {"source": "folder:maple", "target": "folder:pear",
                                                      "shown": shown})[0], 400, shown)
        self.assertEqual(self.stored()["pinned"], ["maple", "folder:orchard"])


class MovedByRoute(Corrected):
    def test_a_whole_project_moved_by_the_assign_route_holds_and_can_be_taken_back(self):
        self.assertEqual(self.post("/api/assign", {"key": "folder:pear", "project": "folder:maple"})[0], 200)
        self.assertEqual(self.names(), ["maple", "orchard"])
        self.assertEqual(self.stored()["assign"], {"folder:pear": "folder:maple"})
        self.post("/api/assign", {"key": "folder:pear", "project": ""})
        self.assertEqual(self.names(), ["maple", "orchard", "pear"])
        self.assertEqual(self.stored()["assign"], {})

    def test_a_project_cannot_be_moved_into_itself_or_into_nothing_by_name(self):
        for body in ({"key": "folder:pear", "project": "folder:pear"}, {"key": "", "project": "folder:maple"}):
            self.assertEqual(self.post("/api/assign", body)[0], 400, body)

    def test_one_session_moved_by_the_assign_route_is_as_before(self):
        self.post("/api/assign", {"key": "fake:c", "project": "folder:maple"})
        self.assertEqual(self.keys("folder:maple"), ["fake:a", "fake:c", "fake:d"])
        self.assertEqual(self.stored()["assign"], {"fake:c": "folder:maple"})


class TwoTabs(Corrected):
    """A tab that has not caught up asks for a move the other way round from one
    already made. The page can never write a ring of moves, so the second move
    turns the first around, the way a merge does, instead of closing a ring that
    would put every click aimed at one card into the other."""

    def test_moving_a_project_into_one_that_was_moved_into_it_turns_the_move_around(self):
        self.seed(assign={"folder:orchard": "folder:maple"})        # the other tab's move
        self.assertEqual(self.post("/api/assign", {"key": "folder:maple", "project": "folder:orchard"})[0], 200)
        self.assertEqual(self.stored()["assign"], {"folder:maple": "folder:orchard"})
        self.assertEqual(self.names(), ["orchard", "pear"])
        self.assertEqual(self.keys("folder:orchard"), ["fake:a", "fake:b", "fake:d"])
        self.assertEqual(self.column("folder:orchard")["merged"],
                         [{"project": "folder:maple", "name": "maple"}])

    def test_the_chip_and_the_picker_of_the_card_it_landed_in_still_land_there(self):
        # What the ring broke: a click aimed at a card put the session in the other one.
        self.seed(assign={"folder:orchard": "folder:maple"})
        self.post("/api/assign", {"key": "folder:maple", "project": "folder:orchard"})
        self.post("/api/assign", {"key": "fake:c", "project": "folder:orchard"})
        self.assertEqual(self.keys("folder:orchard"), ["fake:a", "fake:b", "fake:c", "fake:d"])

    def test_the_move_turns_around_a_ring_of_three_as_well(self):
        # pear into maple (one tab), orchard into pear (another), maple into orchard (a third that is behind).
        self.seed(assign={"folder:pear": "folder:maple", "folder:orchard": "folder:pear"})
        self.assertEqual(self.post("/api/assign", {"key": "folder:maple", "project": "folder:orchard"})[0], 200)
        self.assertEqual(self.stored()["assign"], {"folder:orchard": "folder:pear", "folder:maple": "folder:orchard"})
        self.assertEqual(self.names(), ["pear"])
        self.assertEqual(self.keys("folder:pear"), ["fake:a", "fake:b", "fake:c", "fake:d"])

    def test_a_merge_from_a_tab_that_is_behind_does_not_close_a_ring_of_three_either(self):
        # orchard into maple (one tab), pear into orchard (another); then maple merged into pear.
        self.seed(assign={"folder:orchard": "folder:maple", "folder:pear": "folder:orchard"})
        self.assertEqual(self.post("/api/merge", {"source": "folder:maple", "target": "folder:pear"})[0], 200)
        self.assertEqual(self.stored()["assign"], {"folder:pear": "folder:orchard", "folder:maple": "folder:pear"})
        self.assertEqual(self.names(), ["orchard"])
        self.assertEqual(self.keys("folder:orchard"), ["fake:a", "fake:b", "fake:c", "fake:d"])

    def test_a_move_that_closes_no_ring_leaves_the_other_moves_as_they_are(self):
        self.seed(assign={"folder:orchard": "folder:pear", "fake:c": "folder:maple"})
        self.post("/api/assign", {"key": "folder:maple", "project": "folder:orchard"})
        self.assertEqual(self.stored()["assign"],
                         {"folder:orchard": "folder:pear", "fake:c": "folder:maple", "folder:maple": "folder:orchard"})

    def test_taking_a_move_back_and_moving_a_session_never_touch_the_other_moves(self):
        self.seed(assign={"folder:orchard": "folder:maple"})
        self.post("/api/assign", {"key": "fake:c", "project": "folder:orchard"})
        self.post("/api/assign", {"key": "folder:pear", "project": ""})
        self.assertEqual(self.stored()["assign"], {"folder:orchard": "folder:maple", "fake:c": "folder:orchard"})


if __name__ == "__main__":
    unittest.main()
