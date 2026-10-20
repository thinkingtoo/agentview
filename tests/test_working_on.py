"""The working-on line: the one line a tile says about the job its session is on.

Driven through `roster()` with a fake provider, as `test_columns` is, and
reading what the page would print: the line and where it came from. Names,
titles and prompts are invented.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lines
from test_columns import Base, session

HOSTILE = "<img src=x onerror=alert(1)>"


class Working(Base):
    def setUp(self):
        super().setUp()
        # With a line of its own the card does not say the session titles.
        about = "Sells maple syrup online"
        self.config = {"project_lines": {"folder:maple": about, "folder:my-shop": about}}

    def line(self, *sessions, **kw):
        tile = self.tile(*sessions, **kw)
        return tile["line"], tile["lineSource"]


class Sources(Working):
    def test_your_own_line_comes_first(self):
        self.wrote("a", "Card form wired to the vault")
        self.config["lines"] = {"fake:a": "Saved cards"}
        self.assertEqual(self.line(session("a", title="Checkout form")), ("Saved cards", "own"))

    def test_then_what_the_session_wrote(self):
        self.wrote("a", "Card form wired to the vault")
        self.assertEqual(self.line(session("a", title="Checkout form")),
                         ("Card form wired to the vault", "did"))

    def test_then_the_title(self):
        self.assertEqual(self.line(session("a", title="Checkout form", prompt="Add a retry")),
                         ("Checkout form", "title"))

    def test_with_none_of_those_the_last_prompt_stands_in(self):
        self.assertEqual(self.line(session("a", prompt="Make the cart total show VAT", branch="cart-vat")),
                         ("Make the cart total show VAT", "prompt"))

    def test_a_long_prompt_is_one_line_and_the_page_clips_it(self):
        long = "Make the cart total\nshow VAT " + "and more words " * 40
        line, source = self.line(session("a", prompt=long))
        self.assertEqual((line, source), (" ".join(long.split()), "prompt"))
        self.assertNotIn("\n", line)

    def test_a_line_is_carried_whole_for_the_hover_up_to_a_bound(self):
        own = "Saved cards, the vault, the retry logic and the receipts " * 8
        self.config["lines"] = {"fake:a": own}
        self.assertEqual(self.line(session("a"))[0], own.strip())
        self.config["lines"] = {"fake:a": "word " * 5000}
        line = self.line(session("a"))[0]
        self.assertTrue(line.endswith("\u2026") and 1000 < len(line) <= 1500, len(line))

    def test_with_no_prompt_the_branch_stands_in(self):
        self.assertEqual(self.line(session("a", branch="saved-cards")), ("saved-cards", "place"))

    def test_with_no_branch_either_the_folder_does(self):
        self.config["assign"] = {"fake:a": "maple"}      # worked on in another folder
        self.assertEqual(self.line(session("a", "orchard/api")), ("api", "place"))

    def test_with_nothing_at_all_the_tile_has_no_line(self):
        # The folder is the project's own name, so it says nothing new.
        self.assertEqual(self.line(session("a", "maple")), ("", ""))

    def test_a_session_with_no_folder_and_nothing_else_has_no_line(self):
        self.assertEqual(self.line(session("a", None)), ("", ""))

    def test_the_line_is_one_line_whatever_the_words_were_written_across(self):
        self.assertEqual(self.line(session("a", title="Checkout\n  form")), ("Checkout form", "title"))

    def test_when_your_own_line_repeats_the_project_the_real_title_is_next(self):
        self.config["lines"] = {"fake:a": "Maple"}
        self.assertEqual(self.line(session("a", title="Checkout form", prompt="Add a retry")),
                         ("Checkout form", "title"))

    def test_a_hand_edited_line_that_is_not_words_is_not_a_line(self):
        for bad in (5, True, "   ", ["Saved cards"], {"line": "Saved cards"}):
            with self.subTest(bad=bad):
                self.config["lines"] = {"fake:a": bad}
                tile = self.tile(session("a", title="Checkout form"))
                self.assertEqual((tile["line"], tile["lineSource"]), ("Checkout form", "title"))

    def test_a_title_that_is_only_spaces_is_nothing(self):
        self.assertEqual(self.line(session("a", title="  \n ", prompt="Add a retry")),
                         ("Add a retry", "prompt"))

    def test_markup_in_any_source_reaches_the_page_as_the_text_it_is(self):
        # The page sets it as text (tests/ui_smoke.py checks that); the roster
        # must not strip or mangle it on the way.
        for over, source in (({"title": HOSTILE}, "title"), ({"prompt": HOSTILE}, "prompt"),
                             ({"branch": HOSTILE}, "place")):
            with self.subTest(source=source):
                self.assertEqual(self.line(session("a", **over)), (HOSTILE, source))
        self.config["lines"] = {"fake:b": HOSTILE}
        self.assertEqual(self.line(session("b")), (HOSTILE, "own"))
        self.wrote("c", HOSTILE)
        self.assertEqual(self.line(session("c")), (HOSTILE, "did"))


class Finding(Working):
    def test_the_filter_box_finds_every_line_a_tile_can_show(self):
        # Your own line is laid over the title, and the title comes back when
        # your line only repeats the project: it is on the tile, so it is found.
        self.config["lines"] = {"fake:a": "Maple"}
        tile = self.tile(session("a", title="Checkout form"))
        self.assertEqual(tile["line"], "Checkout form")
        self.assertIn("checkout form", tile["find"])
        self.config["lines"] = {"fake:b": "Saved cards"}
        tile = self.tile(session("b", title="Checkout form"))
        self.assertIn("saved cards", tile["find"])
        self.assertIn("checkout form", tile["find"])

    def test_a_title_that_is_the_line_is_in_the_text_once(self):
        tile = self.tile(session("a", title="Checkout form", prompt="Add a retry"))
        self.assertEqual(tile["find"].count("checkout form"), 1)


class Cost(Working):
    def test_a_huge_prompt_or_title_costs_a_roster_next_to_nothing(self):
        import context
        import working
        # A pasted file as the last prompt is 100 KB of one line of words, and
        # a roster is made every 3 seconds for every session on the machine.
        huge = "word " * 20480
        sessions = [session(f"s{i}", f"project{i % 20}", prompt=huge, title=huge) for i in range(100)]
        # The cost of a card's guessed line is the card's own (ticket 04).
        self.config["project_lines"] = {f"folder:project{i}": "Sells maple syrup online" for i in range(20)}
        self.roster(*sessions)                      # the first one loads the code
        # Counted, not timed: load delays a roster, it does not make it work more. The
        # work is the characters `squash` is handed (10,240,960 before the start of a
        # text was cut, 1,200,960 now, about 0.7 s and 0.1 s of CPU).
        seen, real = [], context.squash
        context.squash = lambda text: seen.append(len(text)) or real(text)
        try:
            got = self.roster(*sessions)
        finally:
            context.squash = real
        self.assertLessEqual(max(seen), working.LOOKED_AT)
        self.assertLess(sum(seen), 2 * len(sessions) * working.LOOKED_AT)
        tile = got["columns"][0]["sessions"][0]
        self.assertEqual(tile["lineSource"], "title")
        self.assertTrue(tile["line"].endswith("\u2026"))
        self.assertLessEqual(len(tile["line"]), 1500)

    def test_only_the_start_of_a_huge_text_is_looked_at(self):
        import context
        import working
        seen, real = [], context.squash
        context.squash = lambda text: seen.append(len(text)) or real(text)
        try:
            got = working.line_of({"name": "Ilse", "title": "word " * 50000})
        finally:
            context.squash = real
        self.assertEqual(got[1], "title")
        self.assertEqual(seen, [working.LOOKED_AT])


class NoRepeats(Working):
    def test_a_line_that_is_the_project_s_name_is_skipped_for_the_next_source(self):
        self.assertEqual(self.line(session("a", title="Maple", prompt="Add a retry")),
                         ("Add a retry", "prompt"))

    def test_so_is_one_that_is_its_own_name(self):
        self.assertEqual(self.line(session("a", name="Handoff review", title="Handoff review",
                                           prompt="Add a retry")),
                         ("Add a retry", "prompt"))

    def test_a_line_that_is_the_project_s_context_line_is_skipped(self):
        self.config["project_lines"]["folder:maple"] = "Quarterly VAT run"
        self.wrote("a", "Quarterly VAT run")
        self.assertEqual(self.line(session("a", title="Checkout form")), ("Checkout form", "title"))

    def test_a_context_line_made_of_the_one_title_is_not_said_twice(self):
        # With no line of its own, a project's card says what its latest
        # session titles say, so the tile with that title has nothing to add.
        self.config = {}
        self.assertEqual(self.line(session("a", title="Checkout form", prompt="Add a retry")),
                         ("Add a retry", "prompt"))
        self.assertEqual(self.line(session("a", title="Checkout form")), ("", ""))

    def test_a_context_line_that_was_cut_is_matched_by_its_whole_text(self):
        whole = "Quarterly VAT run for every client, with the late fees and the reminders " * 3
        self.config["project_lines"]["folder:maple"] = whole
        self.assertEqual(self.line(session("a", title=whole.strip(), prompt="Add a retry")),
                         ("Add a retry", "prompt"))

    def test_case_spacing_and_slug_marks_do_not_hide_a_repeat(self):
        self.assertEqual(self.line(session("a", "my-shop", title="  MY   shop ", prompt="Add a retry")),
                         ("Add a retry", "prompt"))
        self.assertEqual(self.line(session("a", "my-shop", title="Add a retry")), ("Add a retry", "title"))

    def test_the_folder_that_is_the_project_s_slug_is_not_a_line(self):
        self.assertEqual(self.line(session("a", "my-shop")), ("", ""))

    def test_a_branch_that_repeats_the_project_leaves_the_folder(self):
        self.config["assign"] = {"fake:a": "maple"}
        self.assertEqual(self.line(session("a", "orchard/api", branch="maple")), ("api", "place"))

    def test_your_own_name_for_the_project_counts_as_its_name(self):
        self.config["names"] = {"maple": "Syrup shop"}
        self.assertEqual(self.line(session("a", title="Syrup shop", prompt="Add a retry")),
                         ("Add a retry", "prompt"))

    def test_the_column_of_no_project_has_no_name_to_repeat(self):
        self.assertEqual(self.line(session("a", None, title="No project")), ("No project", "title"))


class KeepingTheDid(Working):
    def test_a_busy_session_keeps_its_last_did_through_its_next_prompt(self):
        self.wrote("a", "Card form wired to the vault")
        lines.begin_turn("a", self.lines)            # the next prompt
        self.assertEqual(self.line(session("a", status="busy", title="Checkout form", quietFor=0.1)),
                         ("Card form wired to the vault", "did"))

    def test_an_idle_one_too(self):
        self.wrote("a", "Card form wired to the vault")
        lines.begin_turn("a", self.lines)
        self.assertEqual(self.line(session("a", status="idle", title="Checkout form")),
                         ("Card form wired to the vault", "did"))

    def test_across_many_prompts(self):
        self.wrote("a", "Card form wired to the vault")
        for _ in range(3):
            lines.begin_turn("a", self.lines)
        self.assertEqual(self.line(session("a", title="Checkout form"))[1], "did")

    def test_a_new_did_replaces_it(self):
        self.wrote("a", "Card form wired to the vault")
        lines.begin_turn("a", self.lines)
        lines.write("a", did="Retry logic under test", root=self.lines)
        self.assertEqual(self.line(session("a", title="Checkout form")),
                         ("Retry logic under test", "did"))

    def test_ask_and_n_still_reset_at_each_prompt(self):
        self.wrote("a", "Card form wired to the vault")
        lines.write("a", did="Card form wired to the vault", ask="Which vault?", n=1, root=self.lines)
        before = self.tile(session("a", status="idle"))
        self.assertEqual((before["blocked"], before["need"]), (True, "Which vault?"))
        lines.begin_turn("a", self.lines)
        after = self.tile(session("a", status="busy", quietFor=0.1))
        self.assertEqual((after["blocked"], after["need"], after["line"]),
                         (False, "", "Card form wired to the vault"))

    def test_a_question_found_in_its_words_does_not_cost_it_the_did(self):
        # The Stop hook's stand-in writes the question and no did.
        self.wrote("a", "Card form wired to the vault")
        lines.begin_turn("a", self.lines)
        lines.write("a", did="", ask="Which vault?", n=1, by="read", root=self.lines)
        self.assertEqual(self.line(session("a", title="Checkout form"))[1], "did")

    def test_your_own_line_still_beats_a_kept_did(self):
        self.wrote("a", "Card form wired to the vault")
        lines.begin_turn("a", self.lines)
        self.config["lines"] = {"fake:a": "Saved cards"}
        self.assertEqual(self.line(session("a", title="Checkout form")), ("Saved cards", "own"))

    def test_a_session_that_never_wrote_one_still_has_its_title(self):
        lines.begin_turn("a", self.lines)
        self.assertEqual(self.line(session("a", title="Checkout form", prompt="Add a retry")),
                         ("Checkout form", "title"))


if __name__ == "__main__":
    unittest.main()
