"""Dialogs that wait on the person: what the roster says of a session whose
registry record reads `dialog open`.

Claude Code writes that word for a menu the person opened, and also for the
dialogs it raises itself and that wait on an answer. The second kind carries a
`needs` text, which the Claude reader hands over as `asking` -- a `request`
told by its text, or a `pause` for usage credits. Through `roster()` with fake
providers; every row, text and name is invented, and no `needs` text from a
real session comes into this repo.

Ticket 15: a menu the person opened is not stuck; a dialog with a `needs` text
is Needs you with that text as the reason; "Session paused" for usage is a
Limit; and the chime flags are the ones they always were.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
from test_columns import Base, session
from test_needs_you import INJECTION, Chime
from test_stuck_kinds import failure

USAGE = "choose: continue on usage credits or switch models"
RETRY = "choose: retry on fallback model or edit prompt"
BILLING = "acknowledge the classifier billing notice (Enter continues in auto mode)"
REVIEW = "invented: review the settings before they apply"


def menu(sid="a", **over):
    """A menu the person opened: `dialog open`, nothing asked."""
    return session(sid, status="waiting", waitingFor="dialog open", **over)


def dialog(words, sid="a", **over):
    """A dialog Claude Code raised itself, waiting on a choice."""
    return session(sid, status="waiting", waitingFor="dialog open",
                   asking={"kind": "request", "what": words}, **over)


def paused(words=USAGE, sid="a", **over):
    """`Session paused` for usage credits."""
    return session(sid, status="waiting", waitingFor="dialog open",
                   asking={"kind": "pause", "what": words}, **over)


class Dialogs(Base):
    def stuck(self, *sessions):
        return self.tile(*sessions)["stuck"]

    def test_a_menu_the_person_opened_is_not_stuck(self):
        self.assertIsNone(self.stuck(menu()))

    def test_a_dialog_with_a_needs_text_is_needs_you_and_the_text_is_the_reason(self):
        for words in (BILLING, RETRY, REVIEW, "choose: run ultraplan in the cloud"):
            with self.subTest(words=words):
                self.assertEqual(self.stuck(dialog(words)),
                                 {"kind": "needs", "source": "request",
                                  "reason": words[:1].upper() + words[1:],
                                  "context": {"what": words}})

    def test_the_card_of_a_dialog_says_needs_you_and_counts_it(self):
        got = self.roster(dialog(BILLING))
        self.assertEqual(got["columns"][0]["state"], "needs")
        self.assertEqual(got["counts"], {"needs": 1, "otherStuck": 0, "moving": 0})

    def test_the_card_of_a_menu_does_not(self):
        got = self.roster(menu())
        self.assertNotEqual(got["columns"][0]["state"], "needs")
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 0, "moving": 0})
        self.assertEqual(got["columns"][0]["summary"]["stuck"], 0)

    def test_a_session_paused_for_usage_is_a_limit_not_a_thing_to_decide(self):
        got = self.stuck(paused())
        self.assertEqual({k: got[k] for k in ("kind", "source", "reason")},
                         {"kind": "limit", "source": "dialog", "reason": "Session paused"})
        self.assertEqual(got["context"], {"resetsAt": None, "held": None, "text": USAGE})

    def test_the_card_of_a_pause_says_limit_and_counts_it_among_the_other_stuck(self):
        got = self.roster(paused())
        self.assertEqual(got["columns"][0]["state"], "limit")
        self.assertEqual(got["counts"], {"needs": 0, "otherStuck": 1, "moving": 0})
        self.assertEqual(got["columns"][0]["summary"]["stuck"], 1)

    def test_a_pause_with_the_limit_error_behind_it_says_when_it_resets(self):
        # The transcript already says why: 08's reading of it is richer, and wins.
        reset = int(time.time() * 1000 + 98 * 60000)
        got = self.stuck(paused(failure=failure("limit", held=2.0, resetsAt=reset)))
        self.assertEqual((got["kind"], got["source"], got["reason"]), ("limit", "api", "Rate limit"))
        self.assertEqual(got["context"]["resetsAt"], reset)

    def test_a_pause_does_not_hide_something_more_urgent(self):
        self.assertEqual(self.stuck(paused(failure=failure("error")))["kind"], "error")
        lines.begin_turn("a", self.lines)
        lines.write("a", did="Notes page built.", ask="Which branch?", n=1, by="session", root=self.lines)
        self.assertEqual(self.stuck(paused())["kind"], "needs")

    # What the chime reads is not touched: a named wait is `waiting`, whatever
    # the dialog is, with or without the words it carries.
    def test_the_chime_reads_the_same_blocks_with_or_without_the_words(self):
        def heard(*rows):
            return [{"alarms": b["alarms"], "blocked": b["blocked"], "ready": b["ready"], "busy": b["busy"],
                     "members": [{k: m[k] for k in Chime.READ} for m in b["members"]]}
                    for b in self.roster(*rows)["blocks"]]
        plain = heard(menu())
        self.assertEqual((plain[0]["alarms"], plain[0]["members"][0]["flag"]), (1, "waiting"))
        for row in (dialog(BILLING), paused()):
            self.assertEqual(heard(row), plain)

    # R7: its words are a session's, and the page prints them as text only.
    def test_its_words_are_cut_to_a_label_and_are_text_only(self):
        for row in (dialog, paused):
            with self.subTest(row=row.__name__):
                got = self.stuck(row(INJECTION + "w" * 500))
                words = got["context"].get("what") or got["context"]["text"]
                self.assertLessEqual(len(words), fleet.LABEL_LEN)
                self.assertTrue(words.startswith(INJECTION))

    def test_a_pause_that_says_nothing_is_not_believed(self):
        for value in ({"kind": "pause"}, {"kind": "pause", "what": ""}, {"kind": "pause", "what": "   "},
                      {"kind": "pause", "what": 7}, {"kind": "pause", "what": ["x"]}):
            with self.subTest(value=value):
                self.assertIsNone(self.stuck(session("a", status="waiting", waitingFor="dialog open",
                                                     asking=value)))


if __name__ == "__main__":
    unittest.main()
