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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import projects
from test_columns import Base
from test_providers import Fake, minimal


class Claude(Fake):
    """The provider whose sessions can belong to a boss's track."""
    name = "claude"


class Codex(Fake):
    name = "codex"


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

    def keys(self, column):
        return [t["key"] for t in column["sessions"]]


class Folders(Placed):
    def test_a_folder_that_is_no_repository_is_a_project_by_the_folder_rule(self):
        column = self.roster(sess("a", "/home/alice/Projects/orchard"))["columns"][0]
        self.assertEqual({k: column[k] for k in ("project", "kind", "name", "raw")},
                         {"project": "folder:orchard", "kind": "folder",
                          "name": "orchard", "raw": "orchard"})

    def test_a_repository_and_a_folder_with_the_same_name_are_two_projects(self):
        main = self.repo("orchard")
        got = self.roster(sess("a", main), sess("b", "/home/alice/Projects/orchard"))
        self.assertEqual(self.names(got), ["orchard", "orchard"])
        self.assertEqual({c["kind"] for c in got["columns"]}, {"repository", "folder"})
        self.assertEqual(len({c["project"] for c in got["columns"]}), 2)

    def shelved(self, *repos_in_each):
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
        self.assertEqual(self.names(got), ["No project"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_a_folder_holding_one_repository_is_still_a_project(self):
        self.shelved()
        wrapper = self.folder("Projects", "wrapper")
        self.repo("only", at=wrapper)
        self.assertEqual(self.names(self.roster(sess("a", wrapper))), ["wrapper"])


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
        self.assertEqual(sorted(self.names(got)), ["acme", "bravo", "mono"])
        by = {c["name"]: c for c in got["columns"]}
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
        self.assertEqual(self.names(got), ["acme"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_a_client_folder_of_another_repository_is_another_project(self):
        one, two = self.monorepo("mono"), self.monorepo("other")
        got = self.roster(sess("a", one / "clients" / "acme"),
                          sess("b", two / "clients" / "acme"))
        self.assertEqual(self.names(got), ["acme", "acme"])


class Repositories(Placed):
    def test_worktrees_of_one_repository_share_its_column(self):
        main = self.repo("loom")
        fix = self.worktree(main, "loom-fix")
        got = self.roster(sess("a", main), sess("b", fix))
        self.assertEqual(self.names(got), ["loom"])
        self.assertEqual(got["columns"][0]["kind"], "repository")
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_two_clones_of_one_remote_share_a_column_named_after_the_remote(self):
        one = self.repo("loom")
        again = self.repo("loom-copy", remote="https://example.com/alice/loom.git")
        got = self.roster(sess("a", one), sess("b", again))
        self.assertEqual(self.names(got), ["loom"])
        self.assertEqual(sorted(self.keys(got["columns"][0])), ["fake:a", "fake:b"])

    def test_two_repositories_with_the_same_folder_name_stay_two_columns(self):
        mine = self.repo("loom", at=self.folder("mine"))
        theirs = self.repo("loom", at=self.folder("theirs"),
                           remote="git@example.com:bob/{name}.git")
        got = self.roster(sess("a", mine), sess("b", theirs))
        self.assertEqual(self.names(got), ["loom", "loom"])
        self.assertNotEqual(got["columns"][0]["project"], got["columns"][1]["project"])

    def test_a_repository_with_no_remote_is_known_by_where_its_main_checkout_is(self):
        main = self.repo("scratchpad", remote=None)
        side = self.worktree(main, "scratchpad-side")
        got = self.roster(sess("a", main), sess("b", side))
        self.assertEqual(self.names(got), ["scratchpad"])


if __name__ == "__main__":
    unittest.main()
