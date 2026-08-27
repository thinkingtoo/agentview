import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


class Stuck(unittest.TestCase):
    def test_a_session_waiting_on_you_needs_you_at_once(self):
        # Claude Code reports `waiting` when it has asked something. Nobody is
        # coming unless you look, so there is no grace period.
        self.assertEqual(fleet.classify("waiting", quiet=0.1, after=5), "waiting")

    def test_busy_and_writing_is_simply_working(self):
        # The transcript is the only real heartbeat: `updatedAt` in the peer
        # file does not move while a session works.
        self.assertIsNone(fleet.classify("busy", quiet=0.2, after=5))

    def test_busy_but_silent_for_too_long_is_stuck(self):
        self.assertEqual(fleet.classify("busy", quiet=9.0, after=5), "stuck")

    def test_idle_is_finished_not_stuck_however_long(self):
        # Petra has been idle for 44 hours. That is an abandoned session, and
        # flashing it every day would teach you to ignore the flashing.
        self.assertIsNone(fleet.classify("idle", quiet=2600, after=5))

    def test_a_session_with_no_transcript_is_not_accused(self):
        self.assertIsNone(fleet.classify("busy", quiet=None, after=5))
