"""A project's name and what it is about: the roster's `columns` carry a
display name, a context line with its source, and for a track a status tag
and progress.

Everything goes through `roster()` with fake providers, like `test_columns`
and `test_projects`. Goal files, READMEs, agent instructions and config are
built in a temp dir; nothing here reads the real `~/.claude/pm`, a real
repository, the real config or the brain. Names and texts are invented.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from test_projects import Claude, Placed, TrackFixtures, sess


class Names(TrackFixtures):
    def first(self, *sessions, provider=None):
        return self.roster(*sessions, provider=provider)["columns"][0]

    def test_a_slug_reads_as_words_with_a_capital_and_keeps_the_raw_one(self):
        column = self.first(sess("a", self.repo("saved-cards_form")))
        self.assertEqual((column["name"], column["raw"]), ("Saved cards form", "saved-cards_form"))

    def test_the_brand_stays_lowercase_even_first(self):
        column = self.first(sess("a", self.repo("tiroir-central")))
        self.assertEqual(column["name"], "tiroir central")

    def test_a_track_is_prettified_like_a_repository(self):
        column = self.claude(self.boss("b", self.repo("loom"), "overview-build"))["columns"][0]
        self.assertEqual((column["name"], column["raw"]), ("Overview build", "overview-build"))

    def test_your_own_name_is_shown_exactly_as_you_wrote_it(self):
        self.config = {"names": {"repo:example.com/alice/loom": "loom (old)"}}
        self.assertEqual(self.first(sess("a", self.repo("loom")))["name"], "loom (old)")


FOLDER = "/home/alice/Projects/orchard"      # no repository there: a project by the folder rule
EARLY, MIDDLE, LATE = 1790000000000, 1790000100000, 1790000200000


class ContextLine(TrackFixtures):
    def first(self, *sessions):
        """The first column the roster draws for these sessions."""
        return self.roster(*sessions)["columns"][0]

    def context(self, *sessions):
        return self.first(*sessions)["context"]

    def test_your_own_line_beats_every_source(self):
        loom = self.repo("loom")
        (loom / "README.md").write_text("# loom\n\nA tiny tool that prints reports.\n")
        self.config = {"project_lines": {"repo:example.com/alice/loom": "Quarterly VAT run"}}
        self.assertEqual(self.context(sess("a", loom, title="Fix a thing")),
                         {"source": "own", "line": "Quarterly VAT run",
                          "full": "Quarterly VAT run", "guess": False})

    def test_a_project_with_no_source_offers_its_two_latest_titles_as_a_guess(self):
        got = self.context(sess("a", FOLDER, title="Card form", updatedAt=EARLY),
                           sess("b", FOLDER, title="Retry logic", updatedAt=LATE),
                           sess("c", FOLDER, title="Receipt export", updatedAt=MIDDLE))
        self.assertEqual(got, {"source": "guess", "line": "Retry logic \u00b7 Receipt export",
                               "full": "Retry logic \u00b7 Receipt export", "guess": True})

    def test_the_same_title_twice_is_said_once_and_a_blank_one_not_at_all(self):
        got = self.context(sess("a", FOLDER, title="Card form", updatedAt=LATE),
                           sess("b", FOLDER, title="Card form", updatedAt=MIDDLE),
                           sess("c", FOLDER, title="", updatedAt=EARLY))
        self.assertEqual(got["line"], "Card form")

    def test_a_project_whose_sessions_have_no_title_still_has_a_guess_to_fill_in(self):
        self.assertEqual(self.context(sess("a", FOLDER, title="")),
                         {"source": "guess", "line": "", "full": "", "guess": True})

    def test_the_column_for_sessions_with_no_project_has_no_context_line(self):
        column = self.first(sess("a", ""))
        self.assertEqual((column["kind"], column["context"], column["track"], column["notes"]),
                         ("none", None, None, None))

    def test_your_line_is_cut_at_about_140_characters_and_whole_on_hover(self):
        words = " ".join(f"word{i:02d}" for i in range(40))      # 6 characters and a space each
        self.config = {"project_lines": {"folder:orchard": words}}
        got = self.context(sess("a", FOLDER))
        self.assertEqual(got["full"], words)
        self.assertTrue(got["line"].endswith("\u2026"))
        self.assertTrue(110 <= len(got["line"]) <= 140, len(got["line"]))
        self.assertTrue(words.startswith(got["line"][:-1]))
        self.assertEqual(got["line"][-8], " ")            # cut between words, not inside one

    # -- R9: a track and a repository with one name are two projects ---------

    def test_a_track_and_a_repository_with_one_name_never_share_a_line_or_a_name(self):
        loom, orchard = self.repo("loom"), self.repo("orchard")
        self.config = {"project_lines": {"repo:example.com/alice/orchard": "The shop front"},
                       "names": {"track:orchard": "Orchard push"}}
        got = self.claude(self.boss("b", loom, "orchard"), sess("a", orchard))
        by = {c["project"]: c for c in got["columns"]}
        track, repo = by["track:orchard"], by["repo:example.com/alice/orchard"]
        self.assertEqual((track["name"], track["context"]["source"]), ("Orchard push", "guess"))
        self.assertEqual((repo["name"], repo["context"]["line"]), ("Orchard", "The shop front"))

    def test_a_line_kept_under_a_plain_name_is_nobody_s(self):
        self.config = {"project_lines": {"orchard": "Not an identity"}}
        self.assertEqual(self.context(sess("a", FOLDER))["source"], "guess")


if __name__ == "__main__":
    unittest.main()
