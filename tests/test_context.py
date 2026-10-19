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
    def column(self, *sessions, provider=None):
        return self.roster(*sessions, provider=provider)["columns"][0]

    def test_a_slug_reads_as_words_with_a_capital_and_keeps_the_raw_one(self):
        column = self.column(sess("a", self.repo("saved-cards_form")))
        self.assertEqual((column["name"], column["raw"]), ("Saved cards form", "saved-cards_form"))

    def test_the_brand_stays_lowercase_even_first(self):
        column = self.column(sess("a", self.repo("tiroir-central")))
        self.assertEqual(column["name"], "tiroir central")

    def test_a_track_is_prettified_like_a_repository(self):
        column = self.claude(self.boss("b", self.repo("loom"), "overview-build"))["columns"][0]
        self.assertEqual((column["name"], column["raw"]), ("Overview build", "overview-build"))

    def test_your_own_name_is_shown_exactly_as_you_wrote_it(self):
        self.config = {"names": {"repo:example.com/alice/loom": "loom (old)"}}
        self.assertEqual(self.column(sess("a", self.repo("loom")))["name"], "loom (old)")


if __name__ == "__main__":
    unittest.main()
