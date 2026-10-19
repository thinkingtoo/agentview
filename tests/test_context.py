"""A project's name and what it is about: the roster's `columns` carry a
display name, a context line with its source, and for a track a status tag
and progress.

Everything goes through `roster()` with fake providers, like `test_columns`
and `test_projects`. Goal files, READMEs, agent instructions and config are
built in a temp dir; nothing here reads the real `~/.claude/pm`, a real
repository, the real config or the brain. Names and texts are invented.
"""
import json
import os
import sys
import time
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

    def test_the_brand_is_lowercase_wherever_and_however_it_is_written(self):
        self.assertEqual(self.first(sess("a", self.repo("Tiroir-Central")))["name"], "tiroir Central")
        self.assertEqual(self.first(sess("a", self.repo("My-TIROIR-site")))["name"], "My tiroir site")

    def test_a_track_is_prettified_like_a_repository(self):
        column = self.claude(self.boss("b", self.repo("loom"), "overview-build"))["columns"][0]
        self.assertEqual((column["name"], column["raw"]), ("Overview build", "overview-build"))

    def test_your_own_name_is_shown_exactly_as_you_wrote_it(self):
        self.config = {"names": {"repo:example.com/alice/loom": "loom (old)"}}
        self.assertEqual(self.first(sess("a", self.repo("loom")))["name"], "loom (old)")


FOLDER = "/home/alice/Projects/orchard"      # no repository there: a project by the folder rule
EARLY, MIDDLE, LATE = 1790000000000, 1790000100000, 1790000200000
HOSTILE = "<img src=x onerror=alert(1)>"     # R7: every text reaches the page as text


class Cards(TrackFixtures):
    def first(self, *sessions):
        """The first column the roster draws for these sessions."""
        return self.roster(*sessions)["columns"][0]

    def context(self, *sessions):
        return self.first(*sessions)["context"]


class ContextLine(Cards):
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

    def test_a_line_of_yours_that_is_a_wall_of_text_is_held_to_what_a_hover_can_carry(self):
        self.config = {"project_lines": {"folder:orchard": "word " * 5000}}
        got = self.context(sess("a", FOLDER))
        self.assertLessEqual(len(got["full"]), 1500)
        self.assertTrue(got["line"].endswith("\u2026"))

    def test_markup_in_your_line_or_in_a_title_is_kept_as_the_text_it_is(self):
        self.config = {"project_lines": {"folder:orchard": "Sells " + HOSTILE}}
        self.assertEqual(self.context(sess("a", FOLDER))["line"], "Sells " + HOSTILE)
        self.config = {}
        got = self.context(sess("a", FOLDER, title="Fix " + HOSTILE))
        self.assertEqual((got["source"], got["line"], got["full"]), ("guess", "Fix " + HOSTILE, "Fix " + HOSTILE))

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

    def test_lines_that_are_not_a_table_of_text_are_ignored(self):
        for bad in (None, [], "x", 5):
            self.config = {"project_lines": bad}
            self.assertEqual(self.context(sess("a", FOLDER))["source"], "guess", bad)
        for bad in (5, None, ["x"], "   "):
            self.config = {"project_lines": {"folder:orchard": bad}}
            self.assertEqual(self.context(sess("a", FOLDER))["source"], "guess", bad)

    def test_a_line_kept_under_a_plain_name_is_nobody_s(self):
        self.config = {"project_lines": {"orchard": "Not an identity"}}
        self.assertEqual(self.context(sess("a", FOLDER))["source"], "guess")


class Tracks(Cards):
    def setUp(self):
        super().setUp()
        self.loom = self.repo("loom")          # where the boss of the track below works

    def goal(self, track, outcome="Customers pay with a saved card. Nothing else changes.",
             status="OPEN", boxes=("[x] cart", "[ ] receipt", "[ ] refund"), extra=""):
        """`pm/<track>.goal.md` the way a boss writes it."""
        body = "".join(f"- {b}\n" for b in boxes)
        (self.pm / f"{track}.goal.md").write_text(
            f"# Objective \u2014 {track}\n_Status: {status}_\n\n## Outcome\n{outcome}\n\n"
            f"## Done when\n{body}\n## Deliverables\n- [ ] a thing that is not a criterion\n{extra}")

    def track(self, name="checkout", nogoal=False, **over):
        """The column of a track whose boss works in `loom`; with a goal file unless `nogoal`."""
        if not nogoal:
            self.goal(name, **over)
        return self.claude(self.boss("b", self.loom, name))["columns"][0]

    def test_a_tracks_line_is_the_first_sentence_of_its_outcome_and_the_paragraph_is_the_hover(self):
        got = self.track()["context"]
        self.assertEqual(got, {"source": "goal", "line": "Customers pay with a saved card.",
                               "full": "Customers pay with a saved card. Nothing else changes.",
                               "guess": False})

    def test_a_status_word_is_the_tag_in_whatever_case_it_is_written(self):
        self.assertEqual(self.track(status="open")["track"]["status"], "OPEN")
        self.assertEqual(self.track(status="Met")["track"]["status"], "MET")
        self.assertEqual(self.track(status="parked")["track"]["status"], "")

    def test_a_sentence_ends_before_a_capital_that_is_not_ascii(self):
        got = self.track(outcome="Il sito \u00e8 pronto per i clienti. \u00c8 online da luned\u00ec e accetta pagamenti.")
        self.assertEqual(got["context"]["line"], "Il sito \u00e8 pronto per i clienti.")
        got = self.track(outcome="Wij verkopen appels, e.g. in de winkel. \u00d6vriga delar f\u00f6ljer.")
        self.assertEqual(got["context"]["line"], "Wij verkopen appels, e.g. in de winkel.")

    def test_a_sentence_ends_before_a_digit_too(self):
        got = self.track(outcome="Version 2 ships on Monday. 3 clients use it already.")
        self.assertEqual(got["context"]["line"], "Version 2 ships on Monday.")

    def test_a_goal_still_holding_its_placeholder_has_no_outcome_yet(self):
        got = self.track(outcome="<REPLACE: one sentence.>")
        self.assertEqual(got["context"]["source"], "guess")

    def test_an_outcome_written_over_several_lines_is_one_paragraph(self):
        got = self.track(outcome="Customers pay with\na saved card, e.g. the one\nthey used last. Then done.")["context"]
        self.assertEqual(got["line"], "Customers pay with a saved card, e.g. the one they used last.")
        self.assertTrue(got["full"].endswith("they used last. Then done."))

    def test_a_long_first_sentence_is_cut_and_the_hover_keeps_the_whole_paragraph(self):
        sentence = "Customers pay " + " ".join(["with"] * 60) + " a saved card."
        got = self.track(outcome=sentence + " More.")["context"]
        self.assertTrue(got["line"].endswith("\u2026") and len(got["line"]) <= 140)
        self.assertEqual(got["full"], sentence + " More.")

    def test_a_track_with_no_goal_file_or_no_outcome_in_it_falls_back_to_the_guess(self):
        self.assertEqual(self.track(nogoal=True)["context"]["source"], "guess")
        (self.pm / "checkout.goal.md").write_text("# Objective\n_Status: OPEN_\n\n## Done when\n- [ ] x\n")
        self.assertEqual(self.track(nogoal=True)["context"]["source"], "guess")

    def test_markup_in_the_outcome_is_kept_as_the_text_it_is(self):
        got = self.track(outcome=f"Pay with {HOSTILE} cards. Then done.")["context"]
        self.assertEqual((got["line"], got["full"]), (f"Pay with {HOSTILE} cards.", f"Pay with {HOSTILE} cards. Then done."))

    def test_your_line_beats_the_goal(self):
        self.config = {"project_lines": {"track:checkout": "Mine"}}
        got = self.track()
        self.assertEqual((got["context"]["source"], got["context"]["line"]), ("own", "Mine"))

    def test_only_a_goal_of_that_track_is_ever_read(self):
        # An identity comes from the page; a path in it must not walk out of the folder.
        (self.disk / "secret.goal.md").write_text("## Outcome\nNot for the card.\n")
        self.config = {"assign": {"fake:a": "track:../secret"}}
        got = self.roster(sess("a", self.repo("orchard")))["columns"][0]
        self.assertEqual((got["project"], got["context"]["source"]), ("track:../secret", "guess"))

    def test_an_outcome_written_with_a_bold_label_is_read_like_one_under_a_heading(self):
        for label in ("**Outcome:** Customers pay with a saved card. Nothing else changes.",
                      "**Outcome**: Customers pay with a saved card. Nothing else changes.",
                      "**Outcome:**\nCustomers pay with a saved card. Nothing else changes.",
                      "  **outcome** :  Customers pay with a saved card. Nothing else changes."):
            with self.subTest(label=label):
                (self.pm / "checkout.goal.md").write_text(
                    f"# Objective\n_Status: OPEN_\n\n{label}\n\n**Deliverables:** a thing\n")
                got = self.track(nogoal=True)["context"]
                self.assertEqual((got["source"], got["line"]), ("goal", "Customers pay with a saved card."))
                self.assertEqual(got["full"], "Customers pay with a saved card. Nothing else changes.")

    def test_boxes_under_a_bold_done_when_count_and_the_next_label_or_heading_ends_them(self):
        for opening in ("**Done when:**", "**Done when**:"):
            for after in ("**Deliverables:**\n- [x] a thing that is not a criterion\n",
                          "## Deliverables\n- [x] a thing that is not a criterion\n"):
                with self.subTest(opening=opening, after=after[:12]):
                    (self.pm / "checkout.goal.md").write_text(
                        f"# Objective\n_Status: OPEN_\n\n**Outcome:** Customers pay.\n\n{opening}\n"
                        f"- [x] one\n- [ ] two\n- [x] three\n\n{after}")
                    got = self.track(nogoal=True)["track"]
                    self.assertEqual(got["progress"],
                                     {"done": 2, "total": 3, "text": "2 of 3", "met": False})

    def test_a_bold_done_when_with_a_met_status_shows_done(self):
        (self.pm / "checkout.goal.md").write_text(
            "# Objective\n_Status: MET 2026-10-01_\n\n**Outcome:** Customers pay.\n\n**Done when:**\n- [ ] one\n")
        got = self.track(nogoal=True)["track"]
        self.assertEqual((got["status"], got["progress"]["text"]), ("MET", "done"))

    def test_a_bold_label_inside_a_heading_section_does_not_end_it(self):
        (self.pm / "checkout.goal.md").write_text(
            "# Objective\n_Status: OPEN_\n\n## Outcome\nCustomers pay.\n**Note:** by card.\n\n"
            "## Done when\n- [x] one\n**Note:** the second is next\n- [ ] two\n")
        got = self.track(nogoal=True)
        self.assertEqual(got["context"]["full"], "Customers pay. Note: by card.")
        self.assertEqual(got["track"]["progress"]["text"], "1 of 2")

    def test_a_bold_word_that_is_no_label_does_not_open_a_section(self):
        (self.pm / "checkout.goal.md").write_text(
            "# Objective\n_Status: OPEN_\n\n**Outcome** is what we want here.\n\n## Done when\n- [ ] one\n")
        got = self.track(nogoal=True)
        self.assertEqual(got["context"]["source"], "guess")
        self.assertEqual(got["track"]["progress"]["total"], 1)

    def test_a_heading_with_closing_marks_still_opens_its_section(self):
        (self.pm / "checkout.goal.md").write_text(
            "# Objective\n_Status: OPEN_\n\n## Outcome ##\nCustomers pay.\n\n## Done when ##\n- [x] one\n")
        got = self.track(nogoal=True)
        self.assertEqual((got["context"]["line"], got["track"]["progress"]["text"]), ("Customers pay.", "1 of 1"))

    def test_an_outcome_with_tags_in_it_is_not_a_placeholder(self):
        for outcome, line in (("<b>Customers</b> pay with a saved <i>card</i>. Then done.",
                               "Customers pay with a saved card."),
                              ("<REPLACE: who> pay with a saved <REPLACE: what>", "<REPLACE: who> pay with a saved <REPLACE: what>")):
            with self.subTest(outcome=outcome):
                got = self.track(outcome=outcome)["context"]
                self.assertEqual((got["source"], got["line"]), ("goal", line))

    def test_a_heading_line_of_a_great_many_spaces_costs_nothing(self):
        started = time.monotonic()
        got = self.track(outcome="Customers pay.\n\n### Detail" + " " * 1500 + "reports\n\nMore.")
        self.assertEqual((got["context"]["line"], got["track"]["progress"]["total"]), ("Customers pay.", 3))
        self.assertLess(time.monotonic() - started, 2.0)

    # -- status and progress ---------------------------------------------------

    def test_a_track_shows_its_status_word_and_how_many_boxes_are_ticked(self):
        got = self.track(status="PAUSED \u2014 waiting on the owner")["track"]
        self.assertEqual(got, {"status": "PAUSED",
                               "progress": {"done": 1, "total": 3, "text": "1 of 3", "met": False}})

    def test_a_met_track_shows_done_whatever_its_boxes_say(self):
        got = self.track(status="MET 2026-10-16 \u2014 all done", boxes=("[ ] a", "[ ] b"))["track"]
        self.assertEqual(got["status"], "MET")
        self.assertEqual(got["progress"], {"done": 2, "total": 2, "text": "done", "met": True})

    def test_a_met_track_with_no_boxes_at_all_still_shows_done(self):
        got = self.track(status="MET", boxes=())["track"]
        self.assertEqual(got["progress"], {"done": 0, "total": 0, "text": "done", "met": True})

    def test_a_track_with_no_boxes_shows_a_status_and_no_progress(self):
        got = self.track(boxes=())["track"]
        self.assertEqual(got, {"status": "OPEN", "progress": None})

    def test_only_the_boxes_under_done_when_count_in_any_style_and_not_in_code(self):
        (self.pm / "checkout.goal.md").write_text(
            "# Objective\n_Status: OPEN_\n\n## Outcome\nCustomers pay.\n\n"
            "## Done when\n- [x] one\n* [X] two\n   - [ ] three, indented\n"
            "```\n- [ ] four, in a fence\n```\nnot a box\n\n"
            "## Deliverables\n- [x] five, another section\n")
        got = self.track(nogoal=True)["track"]
        self.assertEqual((got["progress"]["done"], got["progress"]["total"]), (2, 3))

    def test_a_status_that_is_none_of_the_three_words_has_no_tag(self):
        got = self.track(status="BLOCKED on a thing")["track"]
        self.assertEqual(got["status"], "")
        self.assertEqual(got["progress"]["text"], "1 of 3")

    def test_a_repository_has_a_context_line_but_no_status_or_progress(self):
        column = self.first(sess("a", self.loom))
        self.assertIsNone(column["track"])

    def test_the_notes_query_does_not_carry_the_ellipsis_of_a_cut_line(self):
        sentence = "Customers pay " + " ".join(["with"] * 60) + " a saved card."
        got = self.track(outcome=sentence)
        self.assertTrue(got["context"]["line"].endswith("\u2026"))
        self.assertEqual(got["notes"]["query"], "Checkout " + got["context"]["line"][:-1])

    def test_the_notes_query_is_the_name_and_the_line(self):
        self.assertEqual(self.track()["notes"],
                         {"query": "Checkout Customers pay with a saved card."})


class Repositories(Cards):
    def setUp(self):
        super().setUp()
        self.loom = self.repo("loom")

    def put(self, name, text, root=None):
        (root or self.loom).joinpath(name).write_text(text)

    def line(self, root=None):
        return self.context(sess("a", root or self.loom))

    def test_a_repository_says_the_first_prose_paragraph_of_its_readme(self):
        self.put("README.md", "# loom\n\n[![Build](b.svg)](https://ci.example)\n\n"
                              "A tiny tool that prints\nreports for the **shop**.\n\n## Install\nRun `make`.\n")
        self.assertEqual(self.line(), {
            "source": "readme", "line": "A tiny tool that prints reports for the shop.",
            "full": "A tiny tool that prints reports for the shop.", "guess": False})

    def test_a_session_assigned_here_from_another_repository_does_not_lend_its_readme(self):
        zzz, aaa = self.repo("zzz-tool"), self.repo("aaa-dots")
        self.put("README.md", "Tool turns timesheets into invoices.\n", zzz)
        self.put("README.md", "My shell and editor settings.\n", aaa)
        self.config = {"assign": {"fake:b": "repo:example.com/alice/zzz-tool"}}
        got = self.roster(sess("a", zzz), sess("b", aaa))
        self.assertEqual([c["project"] for c in got["columns"]], ["repo:example.com/alice/zzz-tool"])
        self.assertEqual(got["columns"][0]["context"]["line"], "Tool turns timesheets into invoices.")
        self.put("README.md", "Tool turns timesheets into invoices.\n", aaa)
        os.remove(zzz / "README.md")
        self.assertEqual(self.roster(sess("a", zzz), sess("b", aaa))["columns"][0]["context"]["source"], "guess")

    def test_a_badge_row_is_not_prose_however_its_links_are_written(self):
        badges = ["[![npm][npm-image]][npm-url] [![build][build-image]][build-url]",
                  "[![Python](https://img.shields.io/badge/python-3.10%20(min)-blue.svg)](https://python.org)",
                  "![a](a.svg) [![b](b.svg)](https://x.example/p_(q))"]
        for row in badges:
            self.put("README.md", f"# loom\n\n{row}\n\nA tiny tool that prints reports.\n")
            self.assertEqual(self.line()["line"], "A tiny tool that prints reports.", row)

    def test_a_link_whose_address_has_brackets_in_it_is_its_label(self):
        self.put("README.md", "Loom follows [the rule](https://en.wikipedia.org/wiki/Rule_(math)) for reports.\n")
        self.assertEqual(self.line()["line"], "Loom follows the rule for reports.")

    def test_a_readme_that_starts_with_a_byte_order_mark_is_read_like_any_other(self):
        self.loom.joinpath("README.md").write_bytes("\ufeff# loom\n\nA tiny tool that prints reports.\n".encode())
        self.assertEqual(self.line()["line"], "A tiny tool that prints reports.")

    def test_a_list_that_follows_a_line_is_not_part_of_it(self):
        self.put("README.md", "Loom is a tool for:\n- reports\n- invoices\n")
        self.assertEqual(self.line()["line"], "Loom is a tool for:")
        self.put("README.md", "Loom prints reports\n1. fast\n> quoted\n")
        self.assertEqual(self.line()["line"], "Loom prints reports")
        self.put("README.md", "Loom prints reports\nin the year\n2019. Wow\n")
        self.assertEqual(self.line()["line"], "Loom prints reports in the year 2019. Wow")

    def test_headings_badges_html_blocks_lists_tables_quotes_and_code_are_not_prose(self):
        self.put("README.md", "---\ntitle: Loom\n---\n<!-- a comment\nover lines -->\n"
                              "Loom\n====\n\n<p align=\"center\"><img src=\"logo.png\"></p>\n\n"
                              "<h1 align=\"center\"><b>Loom</b> the reports</h1>\n\n"
                              "![badge](b.svg) [![ci](c.svg)](https://ci.example)\n\n"
                              "- not prose\n- a list\n\n| a | b |\n|---|---|\n\n> a quote\n\n"
                              "```\nnot prose either\n```\n\n    indented code\n\n"
                              "---\n\n[ref]: https://example.com\n\nFinally some prose.\n")
        self.assertEqual(self.line()["line"], "Finally some prose.")

    def test_a_setext_title_directly_above_its_text_does_not_hide_the_text(self):
        self.put("README.md", "Loom\n====\nPrints reports for the shop.\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_a_title_underlined_with_dashes_is_a_title_too(self):
        self.put("README.md", "Loom\n---\n\nPrints reports for the shop.\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")
        self.put("README.md", "Loom\n---\nPrints reports for the shop.\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_a_rule_between_paragraphs_is_not_a_title_for_what_follows_it(self):
        self.put("README.md", "Prints reports for the shop.\n\n---\n\nSecond paragraph.\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_a_long_paragraph_is_cut_and_the_hover_keeps_it_whole(self):
        text = "Prints " + " ".join(["reports"] * 40) + " for the shop."
        self.put("README.md", text + "\n")
        got = self.line()
        self.assertTrue(got["line"].endswith("\u2026") and len(got["line"]) <= 140)
        self.assertEqual(got["full"], text)

    def test_without_a_readme_the_agent_instructions_are_next_and_includes_are_skipped(self):
        self.put("AGENTS.md", "# loom \u2014 for agents\n\n@./OTHER.md\n\nThis is the repository of the shop tooling.\n")
        self.put("CLAUDE.md", "@./AGENTS.md\n")
        self.assertEqual(self.line()["line"], "This is the repository of the shop tooling.")
        self.assertEqual(self.line()["source"], "readme")

    def test_a_readme_with_no_prose_hands_over_to_the_instructions_and_those_to_claude_md(self):
        self.put("README.md", "# loom\n\n![logo](l.png)\n")
        self.put("AGENTS.md", "# agents\n")
        self.put("CLAUDE.md", "@./AGENTS.md\n\nClaude-only notes for the shop tooling.\n")
        self.assertEqual(self.line()["line"], "Claude-only notes for the shop tooling.")

    def test_markup_in_the_readme_or_the_instructions_is_kept_as_the_text_it_is(self):
        text = f"Prints {HOSTILE} reports.\n"
        for name in ("README.md", "AGENTS.md", "CLAUDE.md"):
            for old in ("README.md", "AGENTS.md", "CLAUDE.md"):
                (self.loom / old).unlink(missing_ok=True)
            self.put(name, text)
            self.assertEqual(self.line()["line"], f"Prints {HOSTILE} reports.", name)

    def test_a_comment_that_never_closes_ends_the_text_and_costs_nothing(self):
        self.put("README.md", "Prints reports.\n\n" + "<!-- note\n" * 20000)
        started = time.monotonic()
        self.assertEqual(self.line()["line"], "Prints reports.")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_a_heading_line_of_a_great_many_spaces_costs_nothing(self):
        self.put("README.md", "# Loom" + " " * 1500 + "reports\n\nPrints reports for the shop.\n")
        started = time.monotonic()
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_a_heading_with_closing_marks_is_still_a_heading(self):
        self.put("README.md", "# Loom #\n\n## Install ##\n\nPrints reports for the shop.\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_inline_tags_in_a_sentence_leave_the_sentence_and_not_the_tags(self):
        self.put("README.md", "<b>Loom</b> prints reports for the <i>shop</i><br>and <a href=\"x\">its</a> clients.\n")
        self.assertEqual(self.line()["line"], "Loom prints reports for the shop and its clients.")

    def test_an_html_block_runs_to_the_blank_line_and_is_skipped_whole(self):
        self.put("README.md", "<h1 align=\"center\">Loom</h1>\nPrints reports for the shop.\n\n"
                              "<div>\n  <img src=\"logo.png\">\n</div>\nMore about the logo.\n\n"
                              "<img src=\"a.png\"> <img src=\"b.png\">\n\n"
                              "<a href=\"x\"><img src=\"y.png\"></a>\n\n"
                              "<a href=\"x\"><img src=\"y.png\"> Loom</a> prints reports.\n\n"
                              "<banner-note class=\"x\">\nPrints reports.\n\n"
                              "Second paragraph.\n")
        self.assertEqual(self.line()["line"], "Second paragraph.")

    def test_an_html_block_ends_the_paragraph_before_it(self):
        self.put("README.md", "Prints reports for the shop.\n<div>\n  <img src=\"logo.png\">\n</div>\n")
        self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_a_nul_in_the_text_is_not_mistaken_for_a_code_span(self):
        self.put("README.md", "Use `a` and \x000\x00 and `b` here.\n")
        self.assertEqual(self.line()["line"], "Use a and 0 and b here.")

    def test_a_row_of_links_alone_is_not_prose_in_markdown_or_in_html(self):
        rows = ["[English](README.md) | [Fran\u00e7ais](README.fr.md) | [Deutsch](README.de.md)",
                "[English][en] \u00b7 [Fran\u00e7ais][fr]",
                "<a href=\"README.md\">English</a> | <a href=\"README.fr.md\">Fran\u00e7ais</a>",
                "**[Docs](docs/index.md)**",
                "[![ci](c.svg)](https://ci.example) [Docs](docs/index.md)"]
        for row in rows:
            with self.subTest(row=row):
                self.put("README.md", f"# loom\n\n{row}\n\nPrints reports for the shop.\n")
                self.assertEqual(self.line()["line"], "Prints reports for the shop.")

    def test_a_sentence_with_a_link_in_it_is_still_prose(self):
        self.put("README.md", "[Loom](https://loom.example) prints reports for the shop.\n")
        self.assertEqual(self.line()["line"], "Loom prints reports for the shop.")

    def test_markup_in_a_code_span_is_code_and_not_markup(self):
        for text, line in (("Expands `<!-- include: a.md -->` directives in Markdown files.",
                            "Expands <!-- include: a.md --> directives in Markdown files."),
                           ("Flags every unclosed `<!--` in a page.\n\nMore text.",
                            "Flags every unclosed <!-- in a page."),
                           ("Generates `__init__.py` files for Python packages.",
                            "Generates __init__.py files for Python packages."),
                           ("Use `<b>` for bold and `**` for stars.", "Use <b> for bold and ** for stars."),
                           ("See [the `loom` tool](https://loom.example) for reports.",
                            "See the loom tool for reports."),
                           ("Code like `a` and `b` stays, **bold `c`** too.", "Code like a and b stays, bold c too.")):
            with self.subTest(text=text):
                self.put("README.md", text + "\n")
                self.assertEqual(self.line()["line"], line)

    def test_a_comment_after_a_code_span_is_still_a_comment(self):
        self.put("README.md", "Run `make` <!-- hidden --> to build.\n")
        self.assertEqual(self.line()["line"], "Run make to build.")

    def test_a_paragraph_that_is_a_wall_of_text_is_cut_before_it_is_read(self):
        self.put("README.md", "word " * 50000 + "\n")
        got = self.line()
        self.assertTrue(got["line"].endswith("\u2026"))
        self.assertLessEqual(len(got["full"]), 1500)

    def test_a_comment_in_the_middle_of_a_line_is_taken_out_of_it(self):
        self.put("README.md", "Prints <!-- hidden --> reports.\n\n<!-- one\ntwo -->\nAnd more.\n")
        self.assertEqual(self.line()["line"], "Prints reports.")

    def test_the_agent_instructions_come_before_claude_md_when_both_have_prose(self):
        self.put("AGENTS.md", "Instructions for agents.\n")
        self.put("CLAUDE.md", "Notes for Claude.\n")
        self.assertEqual(self.line()["line"], "Instructions for agents.")

    def test_a_readme_in_any_checkout_beats_the_instructions_of_the_main_one(self):
        # The order the spec gives is README, then the instructions; which checkout has
        # which file only matters between files of the same kind.
        self.put("AGENTS.md", "Instructions for agents.\n")
        side = self.worktree(self.loom, "loom-side")
        self.put("README.md", "Prints reports.\n", root=side)
        got = self.roster(sess("a", self.loom), sess("b", side))
        self.assertEqual(got["columns"][0]["context"]["line"], "Prints reports.")

    def test_a_readme_wins_over_the_instructions(self):
        self.put("README.md", "Prints reports.\n")
        self.put("AGENTS.md", "Instructions for agents.\n")
        self.assertEqual(self.line()["line"], "Prints reports.")

    def test_a_file_name_in_another_case_is_still_the_readme(self):
        self.put("readme.md", "Prints reports.\n")
        self.assertEqual(self.line()["line"], "Prints reports.")

    def test_nothing_readable_there_is_a_guess_from_the_titles(self):
        (self.loom / "README.md").mkdir()                       # not a file
        (self.loom / "AGENTS.md").write_bytes(b"\xff\xfe\x00\x01")  # not text
        got = self.context(sess("a", self.loom, title="Card form"))
        self.assertEqual((got["source"], got["line"], got["guess"]), ("guess", "Card form", True))

    def test_your_line_beats_the_readme(self):
        self.put("README.md", "Prints reports.\n")
        self.config = {"project_lines": {"repo:example.com/alice/loom": "Mine"}}
        self.assertEqual(self.line()["source"], "own")

    def test_a_worktree_reads_the_main_checkout_whichever_session_comes_first(self):
        self.put("README.md", "Prints reports.\n")
        side = self.worktree(self.loom, "loom-side")
        self.put("README.md", "A different branch says other things.\n", root=side)
        got = self.roster(sess("a", side, updatedAt=LATE), sess("b", self.loom, updatedAt=EARLY))
        self.assertEqual(got["columns"][0]["context"]["line"], "Prints reports.")

    def test_a_worktree_alone_reads_the_main_checkout_too(self):
        self.put("README.md", "Prints reports.\n")
        side = self.worktree(self.loom, "loom-side")
        self.assertEqual(self.line(side)["line"], "Prints reports.")

    def test_a_client_folder_in_a_repository_is_not_described_by_the_repository(self):
        self.put("README.md", "Prints reports.\n")
        (self.loom / "clients" / "acme").mkdir(parents=True)
        column = self.first(sess("a", self.loom / "clients" / "acme", title="Acme invoices"))
        self.assertEqual((column["kind"], column["context"]["source"]), ("folder", "guess"))

    def test_a_plain_folder_with_a_readme_is_not_read(self):
        # Only a repository's files describe it; a folder has the guess.
        shelf = self.folder("Projects")
        self.config = {"shelves": [str(shelf)]}
        (self.folder("Projects", "orchard") / "README.md").write_text("Sells apples.\n")
        got = self.context(sess("a", self.folder("Projects", "orchard"), title="Cider"))
        self.assertEqual((got["source"], got["line"]), ("guess", "Cider"))


if __name__ == "__main__":
    unittest.main()
