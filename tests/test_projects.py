"""Which project each session lands in: the roster's `columns`, by assignment.

Everything goes through `roster()` with fake providers, the way `test_columns`
does. Nothing here reads the real `~/.claude/pm`, the real tmux or the real
config: git repositories, trackers and config are built in a temp dir, and
the session facts (tmux name, boss, team, track) are handed over by a fake.
Names and texts are invented.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import projects
from test_columns import Base
from test_providers import Fake, minimal


class Claude(Fake):
    """The provider whose sessions can belong to a boss's track."""
    name = "claude"


class Codex(Fake):
    name = "codex"


def fleet_roster(*providers):
    import fleet
    return fleet.roster(providers=list(providers))


def sess(sid, cwd, **over):
    return minimal(id=sid, cwd=str(cwd), **over)


class Placed(Base):
    def setUp(self):
        super().setUp()
        # Not /tmp: the folder rule treats everything there as scratch, and
        # these tests are about what it does with real-looking folders.
        shm = "/dev/shm" if os.path.isdir("/dev/shm") else None
        self.disk = Path(tempfile.mkdtemp(dir=shm))
        self.addCleanup(shutil.rmtree, self.disk, True)
        self.pm = self.disk / "pm"
        self.pm.mkdir()
        projects.pm_dir, was = (lambda: self.pm), projects.pm_dir
        self.addCleanup(setattr, projects, "pm_dir", was)

    # -- a disk to place sessions on --------------------------------------

    def repo(self, name, remote="git@example.com:alice/{name}.git", at=None):
        """A repository with its `.git` folder, and an origin unless told otherwise."""
        path = (at or self.disk) / name
        (path / ".git").mkdir(parents=True)
        if remote:
            (path / ".git" / "config").write_text(
                '[core]\n\tbare = false\n[remote "origin"]\n\turl = '
                + remote.format(name=name) + "\n")
        return path

    def worktree(self, parent, name):
        """A linked worktree beside its parent, the way `git worktree add` lays it out."""
        path = self.disk / name
        path.mkdir()
        admin = parent / ".git" / "worktrees" / name
        admin.mkdir(parents=True)
        (admin / "commondir").write_text("../..\n")
        (path / ".git").write_text(f"gitdir: {admin}\n")
        return path

    def folder(self, *parts):
        path = self.disk.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def names(self, got):
        return [c["name"] for c in got["columns"]]

    def raws(self, got):
        """Which projects there are, by the name they have before any rename or
        prettifying -- and "No project", which has no other."""
        return [c["raw"] or c["name"] for c in got["columns"]]

    def keys(self, column):
        return [t["key"] for t in column["sessions"]]

    def column(self, got, project):
        return next(c for c in got["columns"] if c["project"] == project)


class Folders(Placed):
    def test_a_launch_folder_that_is_not_absolute_is_nowhere(self):
        # It would be read against wherever the server runs, which is a repository.
        self.assertEqual(self.raws(self.roster(sess("a", "src/app"))), ["No project"])

    def test_a_folder_that_is_no_repository_is_a_project_by_the_folder_rule(self):
        column = self.roster(sess("a", "/home/alice/Projects/orchard"))["columns"][0]
        self.assertEqual({k: column[k] for k in ("project", "kind", "name", "raw")},
                         {"project": "folder:orchard", "kind": "folder",
                          "name": "Orchard", "raw": "orchard"})

    def test_a_repository_and_a_folder_with_the_same_name_are_two_projects(self):
        main = self.repo("orchard")
        got = self.roster(sess("a", main), sess("b", "/home/alice/Projects/orchard"))
        self.assertEqual(self.raws(got), ["orchard", "orchard"])
        self.assertEqual({c["kind"] for c in got["columns"]}, {"repository", "folder"})
        self.assertEqual(len({c["project"] for c in got["columns"]}), 2)

    def shelved(self):
        """`<disk>/Projects` as the shelf, with a plain folder holding repositories."""
        shelf = self.folder("Projects")
        self.config = {"shelves": [str(shelf)]}
        return shelf

    def test_a_plain_folder_holding_several_repositories_is_never_a_project(self):
        shelf = self.shelved()
        suite = self.folder("Projects", "suite")
        self.repo("one", at=suite)
        self.repo("two", at=suite)
        got = self.roster(sess("a", suite), sess("b", shelf))
        self.assertEqual(self.raws(got), ["No project"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_two_client_folders_on_a_shelf_never_share_a_column(self):
        self.shelved()
        clients = self.folder("Projects", "clients")
        self.config = {"shelves": [str(self.disk / "Projects"), str(clients)]}
        got = self.roster(sess("a", self.folder("Projects", "clients", "acme")),
                          sess("b", self.folder("Projects", "clients", "bravo")),
                          sess("c", self.folder("Projects", "clients", "acme")))
        self.assertEqual(sorted(self.raws(got)), ["acme", "bravo"])
        self.assertEqual(sorted(len(c["sessions"]) for c in got["columns"]), [1, 2])

    def test_a_folder_that_holds_folders_of_repositories_is_never_a_project_either(self):
        self.shelved()
        tiroir = self.folder("Projects", "tiroir")
        for group in ("o", "v"):
            for name in ("one", "two"):
                self.repo(f"{group}-{name}", at=self.folder("Projects", "tiroir", group))
        got = self.roster(sess("a", tiroir), sess("b", tiroir / "o"))
        self.assertEqual(self.raws(got), ["No project"])

    def test_a_folder_holding_one_repository_is_still_a_project(self):
        self.shelved()
        wrapper = self.folder("Projects", "wrapper")
        self.repo("only", at=wrapper)
        self.assertEqual(self.raws(self.roster(sess("a", wrapper))), ["wrapper"])


class LaunchFolder(Placed):
    def test_a_session_that_works_in_another_repository_keeps_the_column_it_started_in(self):
        home = self.repo("loom")
        elsewhere = self.repo("orchard")
        touched = [str(elsewhere / "src" / f"{n}.py") for n in "abcd"]
        got = self.roster(sess("a", home, paths=touched))
        self.assertEqual(self.raws(got), ["loom"])


class TrackFixtures(Placed):
    def claude(self, *sessions):
        return self.roster(provider=Claude(sessions))

    def boss(self, sid, cwd, track, **over):
        return sess(sid, cwd, name=over.pop("name", "Ilse"), boss=True, track=track, **over)

    def worker(self, sid, cwd, track, **over):
        """A worker claude-boss launched into the tmux session of its track."""
        return sess(sid, cwd, tmux=f"boss-{track}:@3.%5", **over)

    def tracker(self, track, *workers, prose="", elsewhere=()):
        """`pm/<track>.md` as claude-boss writes it: a Roster table of workers,
        and any other table (`elsewhere`) a boss keeps in the same file."""
        rows = "".join(f"| {w} | 13:0.1 %31 | `src/`, notes |\n" for w in workers)
        other = "".join(f"| {w} | waiting on review |\n" for w in elsewhere)
        (self.pm / f"{track}.md").write_text(
            f"# PM Tracker \u2014 {track}\n\n{prose}\n## Roster\n"
            f"| Worker | Pane | Perimetro |\n|---|---|---|\n{rows}\n"
            f"## Pending\n| Who | What |\n|---|---|\n{other}\n## Open blockers\nnone\n")


class Tracks(TrackFixtures):
    def test_a_worker_in_another_repository_than_its_boss_sits_in_the_boss_track_column(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.worker("w", orchard, "checkout", name="Mateo"),
                          self.boss("b", loom, "checkout"))
        self.assertEqual(self.raws(got), ["checkout"])
        column = got["columns"][0]
        self.assertEqual((column["project"], column["kind"], column["raw"]),
                         ("track:checkout", "track", "checkout"))
        self.assertEqual(self.keys(column), ["claude:b", "claude:w"])

    def test_a_track_column_counts_the_movement_of_every_repository_it_spans(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b", loom, "checkout", writes=[0] * 29 + [2]),
                          self.worker("w", orchard, "checkout", name="Mateo", writes=[0] * 29 + [5]))
        column = got["columns"][0]
        self.assertEqual((column["strip"][-1], sum(column["summary"].values())), (7, 2))

    def test_one_repository_holding_two_tracks_is_two_projects(self):
        loom = self.repo("loom")
        got = self.claude(self.boss("b1", loom, "checkout", name="Ilse"),
                          self.worker("w1", loom, "checkout", name="Mateo"),
                          self.boss("b2", loom, "docs", name="Saskia"),
                          self.worker("w2", loom, "docs", name="Odile"),
                          sess("p", loom, name="Femi"))
        self.assertEqual(sorted(self.raws(got)), ["checkout", "docs", "loom"])
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:b2", "claude:w2"])
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/loom")), ["claude:p"])

    def test_a_track_a_repository_a_client_and_a_folder_with_one_name_are_four_projects(self):
        acme_repo = self.repo("acme")
        mono = self.repo("mono")
        (mono / "clients" / "acme").mkdir(parents=True)
        got = self.claude(self.boss("b", self.repo("loom"), "acme"),
                          sess("r", acme_repo),
                          sess("c", mono / "clients" / "acme"),
                          sess("f", "/home/alice/Projects/acme"))
        self.assertEqual(self.raws(got), ["acme"] * 4)
        self.assertEqual(len({c["project"] for c in got["columns"]}), 4)
        self.assertEqual(sorted(c["kind"] for c in got["columns"]),
                         ["folder", "folder", "repository", "track"])

    def test_a_worker_with_no_pane_name_follows_the_boss_that_messaged_it(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b", loom, "checkout", team=["Mateo"]),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.raws(got), ["checkout"])
        self.assertEqual(self.keys(got["columns"][0]), ["claude:b", "claude:w"])

    def test_the_pane_name_beats_the_boss_that_messaged_the_worker(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b1", loom, "checkout", team=["Mateo"]),
                          self.boss("b2", loom, "docs", name="Saskia"),
                          self.worker("w", orchard, "docs", name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:b2", "claude:w"])
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b1"])

    def test_a_worker_two_bosses_of_different_tracks_both_messaged_is_filed_under_neither(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b1", loom, "checkout", team=["Mateo"]),
                          self.boss("b2", loom, "docs", name="Saskia", team=["Mateo"]),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/orchard")),
                         ["claude:w"])

    def test_a_worker_a_boss_without_a_track_messaged_is_not_filed_by_it(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(sess("b", loom, name="Ilse", boss=True, team=["Mateo"]),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(sorted(self.raws(got)), ["loom", "orchard"])

    def test_a_worker_only_the_tracker_names_is_filed_under_that_track(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "Mateo (sonnet)", "Odile")
        got = self.claude(self.boss("b", loom, "checkout"),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b", "claude:w"])

    def test_a_roster_heading_may_carry_a_note_or_a_prefix_as_real_trackers_write_it(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        for i, heading in enumerate(["## Roster (current, max 2)", "## Worker roster", "### Roster"]):
            track = f"track{i}"
            (self.pm / f"{track}.md").write_text(
                f"# PM Tracker\n\n{heading}\n| Worker | Pane |\n|---|---|\n| Mateo | %31 |\n")
            got = self.claude(self.boss("b", loom, track), sess("w", orchard, name="Mateo"))
            self.assertEqual(self.keys(self.column(got, f"track:{track}")), ["claude:b", "claude:w"], heading)

    def test_a_table_under_a_heading_that_only_mentions_the_roster_does_not_name_workers(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        (self.pm / "checkout.md").write_text(
            "# PM Tracker\n\n### Roster correction\n| Who | Was |\n|---|---|\n| Mateo | double-counted |\n")
        got = self.claude(self.boss("b", loom, "checkout"), sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b"])

    def test_a_worker_named_by_two_trackers_is_filed_under_neither(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "Mateo")
        self.tracker("docs", "Mateo")
        got = self.claude(self.boss("b1", loom, "checkout"),
                          self.boss("b2", loom, "docs", name="Saskia"),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/orchard")),
                         ["claude:w"])

    def test_a_retired_worker_and_a_name_in_passing_do_not_count_as_named(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "~~Mateo~~", "Mateo2", elsewhere=["Femi"],
                     prose="Not claimed: Odile (idle), the owner's planning session.\n")
        got = self.claude(self.boss("b", loom, "checkout"),
                          sess("w1", orchard, name="Mateo"),
                          sess("w2", orchard, name="Odile"),
                          sess("w3", orchard, name="Femi"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b"])

    def test_the_boss_that_messaged_a_worker_beats_a_tracker_that_names_it(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("docs", "Mateo")
        got = self.claude(self.boss("b1", loom, "checkout", team=["Mateo"]),
                          self.boss("b2", loom, "docs", name="Saskia"),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b1", "claude:w"])

    def test_when_two_bosses_messaged_a_worker_the_one_tracker_that_lists_it_decides(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("docs", "Mateo")
        got = self.claude(self.boss("b1", loom, "checkout", team=["Mateo"]),
                          self.boss("b2", loom, "docs", name="Saskia", team=["Mateo"]),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:b2", "claude:w"])

    def test_two_bosses_of_one_track_that_both_messaged_a_worker_file_it_under_that_track(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b1", loom, "checkout", team=["Mateo"]),
                          self.boss("b2", loom, "checkout", name="Saskia", team=["Mateo"]),
                          sess("w", orchard, name="Mateo"))
        self.assertEqual(sorted(self.keys(self.column(got, "track:checkout"))),
                         ["claude:b1", "claude:b2", "claude:w"])

    def test_a_stale_pane_name_falls_back_to_the_boss_that_messaged_the_worker(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = self.claude(self.boss("b", loom, "checkout", team=["Mateo"]),
                          self.worker("w", orchard, "gone", name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b", "claude:w"])

    def test_a_stale_pane_name_falls_back_to_the_tracker_that_lists_the_worker(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "Mateo")
        self.tracker("gone", "Mateo")
        got = self.claude(self.boss("b", loom, "checkout"),
                          self.worker("w", orchard, "gone", name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b", "claude:w"])

    def test_the_pane_name_beats_a_tracker_that_names_the_worker(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "Mateo")
        got = self.claude(self.boss("b1", loom, "checkout"),
                          self.boss("b2", loom, "docs", name="Saskia"),
                          self.worker("w", orchard, "docs", name="Mateo"))
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:b2", "claude:w"])

    def test_a_tracker_of_a_track_nobody_leads_files_nobody(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("old", "Mateo")
        got = self.claude(sess("b", loom, name="Ilse"), sess("w", orchard, name="Mateo"))
        self.assertEqual(sorted(self.raws(got)), ["loom", "orchard"])

    def test_each_running_tracker_is_read_once_however_many_sessions_ask(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("checkout", "Odile")
        reads = []
        real = projects._roster_names
        projects._roster_names = lambda track: reads.append(track) or real(track)
        self.addCleanup(setattr, projects, "_named_in", real)
        self.claude(self.boss("b", loom, "checkout"),
                    *[sess(f"w{i}", orchard, name=f"Worker{i}") for i in range(5)])
        self.assertEqual(reads, ["checkout"])

    def test_a_marker_that_is_a_path_makes_no_track(self):
        loom = self.repo("loom")
        got = self.claude(self.boss("b", loom, "../../elsewhere"))
        self.assertEqual(self.raws(got), ["loom"])

    def test_a_track_whose_boss_is_gone_files_nobody(self):
        # The pane still says `boss-old` and a marker for the departed boss
        # is still on disk. Neither is a boss that is running.
        (self.pm / ".boss-sessions").mkdir()
        (self.pm / ".boss-sessions" / "gone-session").write_text("old\n")
        orchard = self.repo("orchard")
        got = self.claude(self.worker("w", orchard, "old", name="Mateo"))
        self.assertEqual(self.raws(got), ["orchard"])

    def test_only_claude_sessions_belong_to_a_track(self):
        # Codex sessions reach the repository, the folder and the guess only.
        loom, orchard = self.repo("loom"), self.repo("orchard")
        got = fleet_roster(Claude([self.boss("b", loom, "checkout")]),
                           Codex([self.worker("x", orchard, "checkout", name="Mateo")]))
        self.assertEqual(sorted(self.raws(got)), ["checkout", "orchard"])


class Bosses(TrackFixtures):
    def test_a_boss_is_where_its_marker_puts_it_whatever_its_pane_is_called(self):
        loom = self.repo("loom")
        got = self.claude(self.boss("b1", loom, "checkout", tmux="boss-docs:@1.%2"),
                          self.boss("b2", loom, "docs", name="Saskia"))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b1"])
        self.assertEqual(self.keys(self.column(got, "track:docs")), ["claude:b2"])

    def test_a_boss_with_no_marker_track_falls_back_to_the_pane_it_runs_in(self):
        loom = self.repo("loom")
        got = self.claude(self.boss("b", loom, "", tmux="boss-checkout:@1.%2"))
        self.assertEqual(self.raws(got), ["checkout"])

    def test_a_boss_with_no_track_at_all_leads_the_column_of_its_repository(self):
        loom = self.repo("loom")
        got = self.claude(sess("w", loom, name="Mateo"),
                          sess("b", loom, name="Ilse", boss=True))
        self.assertEqual(self.keys(got["columns"][0]), ["claude:b", "claude:w"])

    def test_a_boss_with_no_track_is_not_filed_as_a_worker_of_one(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("docs", "Ilse")
        got = self.claude(self.boss("b1", loom, "docs", name="Saskia"),
                          sess("b2", orchard, name="Ilse", boss=True))
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/orchard")), ["claude:b2"])

    def test_a_boss_that_other_signals_point_at_shows_once_and_first(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.tracker("docs", "Ilse", "Mateo")
        got = self.claude(
            self.worker("w", orchard, "checkout", name="Mateo"),
            self.boss("b1", loom, "checkout", name="Ilse", tmux="boss-docs:@1.%2"),
            self.boss("b2", loom, "docs", name="Saskia", team=["Ilse"]))
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b1", "claude:w"])
        every = [k for c in got["columns"] for k in self.keys(c)]
        self.assertEqual(sorted(every), ["claude:b1", "claude:b2", "claude:w"])

    def test_a_session_a_provider_lists_twice_shows_once(self):
        loom = self.repo("loom")
        boss = self.boss("b", loom, "checkout")
        got = self.claude(boss, dict(boss), sess("w", loom, name="Mateo"), sess("w", loom, name="Mateo"))
        every = [k for c in got["columns"] for k in self.keys(c)]
        self.assertEqual(sorted(every), ["claude:b", "claude:w"])
        self.assertEqual(sum(len(c["sessions"]) for c in got["columns"]), 2)

    def test_a_session_listed_twice_keeps_what_the_record_that_knows_it_leads_says(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        plain = sess("b", loom, name="Ilse")
        boss = self.boss("b", loom, "checkout", name="Ilse")
        for records in ([plain, boss], [boss, plain]):
            got = self.claude(*records, self.worker("w", orchard, "checkout", name="Mateo"))
            self.assertEqual(self.keys(self.column(got, "track:checkout")),
                             ["claude:b", "claude:w"], records)
            self.assertEqual(self.column(got, "track:checkout")["sessions"][0]["tags"], ["boss"])

    def test_a_routine_with_a_track_signal_is_in_no_column(self):
        loom = self.repo("loom")
        got = self.claude(self.boss("b", loom, "checkout"),
                          self.worker("r", loom, "checkout", name="Mateo", routine="nightly-report"))
        self.assertEqual(self.keys(got["columns"][0]), ["claude:b"])


class Renames(TrackFixtures):
    def test_a_project_renamed_to_the_name_of_another_stays_a_project_of_its_own(self):
        loom, acme = self.repo("loom"), self.repo("acme")
        self.config = {"names": {"repo:example.com/alice/loom": "Acme"}}
        got = self.claude(sess("a", loom), sess("b", acme),
                          self.boss("c", self.repo("orchard"), "acme"))
        self.assertEqual(self.names(got), ["Acme", "Acme", "Acme"])
        self.assertEqual(len({c["project"] for c in got["columns"]}), 3)


class Order(TrackFixtures):
    def mixed(self):
        """A track pair, two repositories, a folder and a session with no project."""
        loom, orchard = self.repo("loom"), self.repo("orchard")
        return [self.boss("b1", loom, "checkout", name="Ilse"),
                self.boss("b2", loom, "docs", name="Saskia"),
                sess("r1", loom, name="Femi"), sess("r2", orchard, name="Odile"),
                sess("f", "/home/alice/Projects/maple", name="Rania"),
                sess("n", "", name="Kasper")]

    def test_tracks_then_repositories_then_folders_then_no_project(self):
        self.assertEqual(self.raws(self.claude(*self.mixed())),
                         ["checkout", "docs", "loom", "orchard", "maple", "No project"])

    def test_pinned_projects_lead_in_the_order_they_were_pinned(self):
        self.config = {"pinned": ["repo:example.com/alice/orchard", "folder:maple", "track:docs"]}
        self.assertEqual(self.raws(self.claude(*self.mixed())),
                         ["orchard", "maple", "docs", "checkout", "loom", "No project"])

    def test_a_pin_from_before_projects_had_identities_still_pins_by_name(self):
        self.config = {"pinned": ["orchard", "checkout"]}
        self.assertEqual(self.raws(self.claude(*self.mixed()))[:2], ["orchard", "checkout"])

    def test_a_pin_by_identity_pins_only_that_project(self):
        # A repository named like a track is not the track.
        loom = self.repo("loom")
        acme = self.repo("acme")
        self.config = {"pinned": ["repo:example.com/alice/acme"]}
        got = self.claude(self.boss("b", loom, "acme"), sess("r", acme))
        self.assertEqual([c["project"] for c in got["columns"]],
                         ["repo:example.com/alice/acme", "track:acme"])

    def test_no_project_stays_last_even_when_it_is_pinned(self):
        self.config = {"pinned": [""]}
        self.assertEqual(self.raws(self.claude(*self.mixed()))[-1], "No project")

    def test_projects_of_a_kind_keep_their_places_whatever_their_sessions_do(self):
        # A column that jumps sideways because a session woke up is the
        # reshuffling the overview exists to stop.
        loom, orchard = self.repo("loom"), self.repo("orchard")
        quiet = [sess("a", loom, status="idle"), sess("b", orchard, status="idle")]
        busy = [sess("a", loom, status="idle"),
                sess("b", orchard, status="waiting", waitingFor="input needed", updatedAt=1790000900000)]
        self.assertEqual(self.raws(self.claude(*quiet)), ["loom", "orchard"])
        self.assertEqual(self.raws(self.claude(*busy)), ["loom", "orchard"])

    def test_projects_of_a_kind_go_by_name_without_regard_to_case(self):
        got = self.claude(sess("a", self.repo("Zebra")), sess("b", self.repo("apple")),
                          sess("c", self.repo("Mango")))
        self.assertEqual(self.raws(got), ["apple", "Mango", "Zebra"])


class NoProject(Placed):
    def test_you_can_rename_the_column_for_sessions_with_no_project(self):
        self.config = {"names": {"No project": "Other projects"}}
        column = self.roster(sess("a", ""))["columns"][0]
        self.assertEqual((column["name"], column["kind"], column["project"]),
                         ("Other projects", "none", ""))


class OwnSetting(Placed):
    def test_a_session_you_assigned_by_name_joins_the_project_that_carries_that_name(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"fake:a": "loom"}}
        got = self.roster(sess("a", orchard), sess("b", loom))
        self.assertEqual(self.raws(got), ["loom"])
        self.assertEqual(got["columns"][0]["kind"], "repository")
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_a_name_two_projects_carry_goes_to_the_one_that_comes_first_in_the_columns(self):
        # A track, a repository and a folder can all be called "loom". A plain
        # name is the old way of saying it, so it takes the order the columns
        # have: track, then repository, then folder.
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"claude:a": "loom"}}
        got = self.roster(provider=Claude([
            sess("b", orchard, name="Ilse", boss=True, track="loom"),
            sess("p", loom, name="Femi"),
            sess("a", self.repo("elsewhere"), name="Odile")]))
        self.assertEqual(self.keys(self.column(got, "track:loom")), ["claude:b", "claude:a"])
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/loom")), ["claude:p"])

    def test_a_session_you_assigned_by_identity_joins_that_project_even_alone(self):
        orchard = self.repo("orchard")
        self.config = {"assign": {"fake:a": "repo:example.com/alice/loom"}}
        got = self.roster(sess("a", orchard))
        self.assertEqual((got["columns"][0]["project"], got["columns"][0]["name"],
                          got["columns"][0]["kind"]),
                         ("repo:example.com/alice/loom", "Loom", "repository"))

    def test_your_own_setting_beats_the_boss_track(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"assign": {"claude:w": "repo:example.com/alice/orchard"}}
        got = self.roster(provider=Claude([
            sess("b", loom, name="Ilse", boss=True, track="checkout"),
            sess("w", orchard, name="Mateo", tmux="boss-checkout:@1.%2")]))
        self.assertEqual(self.keys(self.column(got, "repo:example.com/alice/orchard")), ["claude:w"])
        self.assertEqual(self.keys(self.column(got, "track:checkout")), ["claude:b"])

    def test_a_label_the_folder_rule_gave_before_still_finds_its_project(self):
        # Assignments were made against `client › project` labels. A session
        # that belongs where such a label was is still put there.
        shelf = self.folder("Projects")
        lead = self.repo("lead-engine", at=self.folder("Projects", "agency"))
        self.config = {"shelves": [str(shelf)],
                       "assign": {"fake:a": "agency › lead-engine"}}
        got = self.roster(sess("a", self.repo("elsewhere")), sess("b", lead))
        self.assertEqual(self.raws(got), ["lead-engine"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_a_name_no_project_carries_starts_a_folder_project(self):
        orchard = self.repo("orchard")
        self.config = {"assign": {"fake:a": "Invoice tool"}}
        column = self.roster(sess("a", orchard))["columns"][0]
        self.assertEqual((column["project"], column["name"], column["kind"]),
                         ("folder:Invoice tool", "Invoice tool", "folder"))


class Guess(Placed):
    def lost(self, **over):
        """A session launched on a shelf, which is nobody's project."""
        shelf = self.folder("Projects")
        self.config = {"shelves": [str(shelf)]}
        return sess("a", shelf, **over)

    def test_a_session_on_a_shelf_that_works_in_one_repository_is_offered_that_project(self):
        orchard = self.repo("orchard")
        touched = [str(orchard / "src" / f"{n}.py") for n in "abc"]
        got = self.roster(self.lost(paths=touched))
        self.assertEqual(self.raws(got), ["No project"])
        self.assertEqual(got["columns"][0]["sessions"][0]["suggestion"],
                         {"project": "repo:example.com/alice/orchard", "name": "Orchard"})

    def test_too_few_files_or_no_clear_favourite_is_no_suggestion(self):
        orchard, loom = self.repo("orchard"), self.repo("loom")
        few = [str(orchard / "a.py"), str(orchard / "b.py")]
        split = [str(orchard / f"{n}.py") for n in "abc"] + [str(loom / f"{n}.py") for n in "abc"]
        for paths in ([], few, split):
            tile = self.roster(self.lost(paths=paths))["columns"][0]["sessions"][0]
            self.assertIsNone(tile["suggestion"], paths)

    def test_a_relative_path_is_not_a_place_to_look_for_a_project(self):
        # It would be read against wherever the server happens to run, which
        # is itself a repository.
        tile = self.roster(self.lost(paths=["src/a.py", "src/b.py", "src/c.py"]))[
            "columns"][0]["sessions"][0]
        self.assertIsNone(tile["suggestion"])

    def test_a_session_that_has_a_project_is_offered_nothing(self):
        orchard = self.repo("orchard")
        loom = self.repo("loom")
        touched = [str(orchard / f"{n}.py") for n in "abc"]
        tile = self.roster(sess("a", loom, paths=touched))["columns"][0]["sessions"][0]
        self.assertIsNone(tile["suggestion"])

    def test_the_paths_a_session_touched_do_not_travel_to_the_page(self):
        orchard = self.repo("orchard")
        got = self.roster(self.lost(paths=[str(orchard / "a.py")]))
        self.assertNotIn("paths", got["blocks"][0]["members"][0])


class Edges(Placed):
    def test_a_repository_at_home_does_not_swallow_the_folders_under_it(self):
        home = self.folder("home")
        (home / ".git").mkdir()
        (home / ".git" / "config").write_text('[remote "origin"]\n\turl = git@example.com:alice/dotfiles.git\n')
        shelf = self.folder("home", "Projects")
        self.config = {"shelves": [str(shelf)]}
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            got = self.roster(sess("a", self.folder("home", "Projects", "maple")))
        self.assertEqual(self.raws(got), ["maple"])

    def test_a_gitlink_that_is_not_text_does_not_stop_the_page(self):
        odd = self.folder("odd")
        (odd / ".git").write_bytes(b"\xff\xfe\x00gitdir")
        got = self.roster(sess("a", odd))
        self.assertEqual((self.raws(got), got["columns"][0]["kind"]), (["odd"], "folder"))

    def test_a_worktree_whose_commondir_is_not_text_is_still_a_project(self):
        parent = self.repo("suite")
        tree = self.worktree(parent, "suite-wt")
        (parent / ".git" / "worktrees" / "suite-wt" / "commondir").write_bytes(b"\xff\xfe\x00")
        got = self.roster(sess("a", tree))
        self.assertEqual(len(got["columns"]), 1)

    def test_a_submodule_is_a_repository_of_its_own(self):
        parent = self.repo("suite")
        inner = self.folder("suite", "vendor", "lib")
        admin = parent / ".git" / "modules" / "lib"
        admin.mkdir(parents=True)
        (admin / "config").write_text('[remote "origin"]\n\turl = https://example.com/bob/lib.git\n')
        (inner / ".git").write_text("gitdir: ../../.git/modules/lib\n")
        column = self.roster(sess("a", inner))["columns"][0]
        self.assertEqual((column["project"], column["kind"]), ("repo:example.com/bob/lib", "repository"))


class Clients(Placed):
    def monorepo(self, name="mono"):
        main = self.repo(name)
        for client in ("acme", "bravo"):
            (main / "clients" / client).mkdir(parents=True)
        return main

    def test_each_client_folder_is_its_own_project_and_never_shares(self):
        main = self.monorepo()
        got = self.roster(sess("a", main / "clients" / "acme"),
                          sess("b", main / "clients" / "bravo"),
                          sess("c", main))
        self.assertEqual(sorted(self.raws(got)), ["acme", "bravo", "mono"])
        by = {c["raw"]: c for c in got["columns"]}
        self.assertEqual(self.keys(by["acme"]), ["fake:a"])
        self.assertEqual(self.keys(by["bravo"]), ["fake:b"])
        self.assertEqual(self.keys(by["mono"]), ["fake:c"])
        self.assertEqual(by["acme"]["kind"], "folder")

    def test_a_worktree_of_the_repository_keeps_the_client_with_the_main_checkout(self):
        main = self.monorepo()
        side = self.worktree(main, "mono-side")
        (side / "clients" / "acme").mkdir(parents=True)
        got = self.roster(sess("a", main / "clients" / "acme" / "site"),
                          sess("b", side / "clients" / "acme"))
        self.assertEqual(self.raws(got), ["acme"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_when_the_repository_is_the_clients_folder_each_folder_in_it_is_a_client(self):
        clients = self.repo("clients")
        for client in ("acme", "bravo"):
            (clients / client).mkdir()
        got = self.roster(sess("a", clients / "acme"), sess("b", clients / "bravo" / "site"),
                          sess("c", clients))
        self.assertEqual(sorted(self.raws(got)), ["acme", "bravo", "clients"])

    def test_a_client_folder_of_another_repository_is_another_project(self):
        one, two = self.monorepo("mono"), self.monorepo("other")
        got = self.roster(sess("a", one / "clients" / "acme"),
                          sess("b", two / "clients" / "acme"))
        self.assertEqual(self.raws(got), ["acme", "acme"])


class Repositories(Placed):
    def test_worktrees_of_one_repository_share_its_column(self):
        main = self.repo("loom")
        fix = self.worktree(main, "loom-fix")
        got = self.roster(sess("a", main), sess("b", fix))
        self.assertEqual(self.raws(got), ["loom"])
        self.assertEqual(got["columns"][0]["kind"], "repository")
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_two_clones_of_one_remote_share_a_column_named_after_the_remote(self):
        one = self.repo("loom")
        again = self.repo("loom-copy", remote="https://example.com/alice/loom.git")
        got = self.roster(sess("a", one), sess("b", again))
        self.assertEqual(self.raws(got), ["loom"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_two_repositories_with_the_same_folder_name_stay_two_columns(self):
        mine = self.repo("loom", at=self.folder("mine"))
        theirs = self.repo("loom", at=self.folder("theirs"),
                           remote="git@example.com:bob/{name}.git")
        got = self.roster(sess("a", mine), sess("b", theirs))
        self.assertEqual(self.raws(got), ["loom", "loom"])
        self.assertNotEqual(got["columns"][0]["project"], got["columns"][1]["project"])

    def test_a_repository_reached_through_a_link_is_the_one_its_worktree_is_in(self):
        main = self.repo("scratchpad", remote=None)
        side = self.worktree(main, "scratchpad-side")
        link = self.disk / "shortcut"
        link.symlink_to(main)
        got = self.roster(sess("a", link), sess("b", side))
        self.assertEqual(self.raws(got), ["scratchpad"])

    def test_a_repository_with_no_remote_is_known_by_where_its_main_checkout_is(self):
        main = self.repo("scratchpad", remote=None)
        side = self.worktree(main, "scratchpad-side")
        got = self.roster(sess("a", main), sess("b", side))
        self.assertEqual(self.raws(got), ["scratchpad"])


if __name__ == "__main__":
    unittest.main()
