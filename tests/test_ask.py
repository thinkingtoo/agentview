"""Reading an ask out of the last thing a session said.

The fallback path. A session that wrote its own line has already said what
it wants; this is for the ones that have not -- everything running before
the hook existed, and the stops where Claude Code discards the block.

Deliberately conservative. Finding nothing is what makes the hook ask the
session directly, so a miss here costs a turn, and a false ask costs you a
trip to a terminal that wanted nothing.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fleet


def fixture(name):
    return (HERE / "data" / name).read_text(encoding="utf-8")


class Counting(unittest.TestCase):
    def test_a_message_that_asks_nothing_wants_nothing(self):
        # Halima, mid-work: a note about what she is doing next.
        said = ("Un file da riformattare è mio, l'altro è di Astrid ed è già "
                "su `dev`. Sistemo i miei e poi verifico il suo.")
        self.assertEqual(fleet.ask_from(said), ("", 0))

    def test_one_question_keeps_its_own_words(self):
        # Rashid, ending on the question after a list of findings.
        said = ("- No `AGENTS.md` / `CLAUDE.md` in the repo. I can drop in "
                "the starter if you want project-level instructions there.\n\n"
                "What do you want to do in it?")
        self.assertEqual(fleet.ask_from(said),
                         ("What do you want to do in it?", 1))

    def test_four_questions_are_counted_not_quoted(self):
        # The round of this very conversation that asked Q13 through Q16.
        # Quoting the first of four would misrepresent the size of the job.
        ask, n = fleet.ask_from(fixture("four-questions.txt"))
        self.assertEqual(n, 4)
        self.assertEqual(ask, "")

    def test_a_question_body_does_not_count_twice(self):
        # The round that asked Q1, Q2 and Q3 -- Q1's body carries a second
        # question mark spelling out the choice. It is one question.
        self.assertEqual(fleet.ask_from(fixture("three-questions.txt"))[1], 3)

    def test_an_ask_with_no_question_mark_is_missed_on_purpose(self):
        # Janusz's shape: an imperative that plainly wants an answer. The
        # hook blocks on this and the session writes its own line; guessing
        # here would flag every message that contains a colon.
        said = "Dis-moi : presse-papiers, brouillon Gmail, ou tu le copies toi-même."
        self.assertEqual(fleet.ask_from(said), ("", 0))


class WhatIsNotProse(unittest.TestCase):
    def test_a_question_inside_a_code_block_is_not_an_ask(self):
        said = "Here is the check:\n\n```\ngrep -c '?' file   # how many?\n```"
        self.assertEqual(fleet.ask_from(said), ("", 0))

    def test_a_long_single_question_is_clipped(self):
        said = "So, " + "x" * 400 + "?"
        ask, n = fleet.ask_from(said)
        self.assertEqual(n, 1)
        self.assertLessEqual(len(ask), fleet.ASK_LIMIT)

    def test_nothing_said_asks_nothing(self):
        self.assertEqual(fleet.ask_from(""), ("", 0))
