"""Who leads a project block.

A block of five where the third row is the one asking makes you read all
five. What wants you goes first.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


def member(name, flag=None, status="idle", blocked=False, at=0):
    return {"name": name, "flag": flag, "status": status,
            "blocked": blocked, "updatedAt": at}


def names(members):
    return [m["name"] for m in fleet.order_members(members)]


class Leading(unittest.TestCase):
    def test_a_blocked_session_leads_a_block_of_finished_ones(self):
        got = names([member("done", "ready", at=9),
                     member("asking", "ready", blocked=True, at=1),
                     member("also-done", "ready", at=8)])
        self.assertEqual(got[0], "asking")

    def test_waiting_still_ranks_with_blocked(self):
        # Both are stopped on you. Recency decides between them; neither is
        # made to wait behind the other for what it is called.
        got = names([member("blocked", "ready", blocked=True, at=1),
                     member("waiting", "waiting", at=2)])
        self.assertEqual(got, ["waiting", "blocked"])

    def test_a_finished_session_still_beats_a_working_one(self):
        got = names([member("working", None, status="busy", at=9),
                     member("finished", "ready", at=1)])
        self.assertEqual(got, ["finished", "working"])

    def test_ties_break_on_the_most_recent(self):
        got = names([member("older", "ready", at=1), member("newer", "ready", at=5)])
        self.assertEqual(got, ["newer", "older"])

    def test_a_busy_session_is_never_blocked_so_never_leads(self):
        got = names([member("busy", None, status="busy", at=9),
                     member("idle", None, at=1)])
        self.assertEqual(got, ["busy", "idle"])
