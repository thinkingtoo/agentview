"""Remote Control from the phone: `/rc <name>` is typed only into an empty prompt.

The screens are copied from real panes on 2026-11-20: an idle boss, a boss with
a question open (a /rc there would have picked "Ja, alle zes"), and a boss
already under Remote Control whose /rc opened a dialog that filled the pane.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jump
import remotectl

RULE = "─" * 60
IDLE = f"""✻ Worked for 4s · done 8:22 PM
                       new task? /clear to save 158.7k tokens
{RULE}
❯
{RULE}
  Kasper [boss] │ Model: Opus 5.5 | Ctx: 158.6k
"""
QUESTION = f"""{RULE}
 Doorgaan?
❯ 1. Ja, alle zes (Recommended)
     Perla merget #10 en Bashir daarna #35-#39 in volgorde.
{RULE}
  5. Chat about this
Enter to select · ↑/↓ to navigate · Esc to cancel
"""
DIALOG = """✻ Cogitated for 3s · done 2:15 AM
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
   Remote Control
   This session is available in the Claude mobile app and
   at
   https://claude.ai/code/session_01V4g3Kks39YVBdEbqUURabF. ↓
"""
TYPED = f"""{RULE}
❯ /rc half a message
{RULE}
"""


def session(**kw):
    s = {"id": "s1", "name": "Kasper", "pid": 4242, "status": "idle", "waitingFor": "",
         "tmux": "boss-chienvert-france:@3.%168", "boss": True, "track": "", "remote": ""}
    s.update(kw)
    return s


class Name(unittest.TestCase):
    def test_boss_and_concierge_are_named_for_their_track(self):
        self.assertEqual(remotectl.name_for(session()), "chienvert-france-boss")
        self.assertEqual(remotectl.name_for(session(boss=False, name="Naya"), concierge=True),
                         "chienvert-france-concierge")

    def test_the_boss_tracker_wins_over_the_tmux_session(self):
        self.assertEqual(remotectl.name_for(session(track="cross-track", tmux="x:@1.%2")), "cross-track-boss")

    def test_a_worker_keeps_its_own_name(self):
        self.assertEqual(remotectl.name_for(session(boss=False, name="Kenji", tmux="cross-track:@1.%192")),
                         "cross-track-Kenji")

    def test_an_unnamed_worker_is_named_for_its_track_alone(self):
        self.assertEqual(remotectl.name_for(session(boss=False, name="(unnamed)", tmux="t1:@1.%2")), "t1")

    def test_a_numbered_tmux_session_is_no_track(self):
        self.assertEqual(remotectl.name_for(session(boss=False, name="Bram", tmux="34:@1.%199")), "Bram")

    def test_nothing_but_safe_characters_reaches_the_terminal(self):
        got = remotectl.name_for(session(boss=False, name="a; rm -rf ~ $(x)", tmux="t:@1.%2"))
        self.assertRegex(got, r"^[A-Za-z0-9._-]+$")


class Screen(unittest.TestCase):
    def test_an_empty_input_box_is_a_prompt(self):
        self.assertTrue(remotectl.prompt_is_empty(IDLE))

    def test_a_question_is_not(self):
        self.assertFalse(remotectl.prompt_is_empty(QUESTION))

    def test_a_dialog_is_not(self):
        self.assertFalse(remotectl.prompt_is_empty(DIALOG))

    def test_half_a_message_is_not(self):
        self.assertFalse(remotectl.prompt_is_empty(TYPED))


class Start(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, jump, "tmux_target", jump.tmux_target)
        jump.tmux_target = lambda pid, proc="/proc": "boss-chienvert-france:@3.%168"
        self.addCleanup(remotectl._TYPED.clear)
        self.ran = []
        self.screen = IDLE
        self.front = "0 claude"
        self.t = 0

    def run_(self, argv, timeout=4):
        self.ran.append(argv)
        out = {"capture-pane": self.screen, "display-message": self.front}.get(argv[1], "")
        return subprocess.CompletedProcess(argv, 0, out, "")

    def clock(self):
        return self.t

    def sleep(self, n):
        self.t += n

    def start(self, s, reread=None):
        reread = reread or (lambda: s)
        return remotectl.start(s, reread=reread, run=self.run_, sleep=self.sleep, clock=self.clock)

    def typed(self):
        return [a for a in self.ran if a[1] == "send-keys"]

    def test_escapes_then_types_the_command_and_returns_the_link(self):
        url = "https://claude.ai/code/session_01abc"
        reads = iter([session()] + [session(remote=url)] * 50)
        out = self.start(session(), reread=lambda: next(reads))
        self.assertEqual(out, {"ok": True, "url": url, "name": "chienvert-france-boss"})
        self.assertEqual(self.typed(), [
            ["tmux", "send-keys", "-t", "%168", "Escape"],
            ["tmux", "send-keys", "-t", "%168", "-l", "/rc chienvert-france-boss"],
            ["tmux", "send-keys", "-t", "%168", "Enter"]])

    def test_a_question_closed_by_the_escape_is_waited_out(self):
        reads = iter([session(status="waiting")] * 2 + [session()] * 50)
        out = self.start(session(status="waiting", waitingFor="question"), reread=lambda: next(reads))
        self.assertIn(["tmux", "send-keys", "-t", "%168", "-l", "/rc chienvert-france-boss"], self.typed())
        self.assertEqual(out["name"], "chienvert-france-boss")

    def test_a_session_that_starts_working_after_the_escape_is_left_alone(self):
        out = self.start(session(), reread=lambda: session(status="busy"))
        self.assertEqual(out["reason"], "busy: busy")
        self.assertEqual(self.typed(), [["tmux", "send-keys", "-t", "%168", "Escape"]])

    def test_rc_is_never_typed_twice_while_its_link_is_on_the_way(self):
        self.start(session())
        self.ran.clear()
        out = self.start(session())
        self.assertFalse(out["ok"])
        self.assertEqual(self.typed(), [])

    def test_copy_mode_or_a_shell_in_front_is_refused_before_any_key(self):
        for front in ("1 claude", "0 bash"):
            self.front = front
            self.assertFalse(self.start(session())["ok"])
        self.assertEqual(self.typed(), [])

    def test_a_session_with_a_link_is_not_touched(self):
        out = self.start(session(remote="https://claude.ai/code/session_x"))
        self.assertTrue(out["ok"])
        self.assertEqual(self.ran, [])

    def test_a_busy_session_is_refused_untouched(self):
        self.assertFalse(self.start(session(status="busy"))["ok"])
        self.assertEqual(self.ran, [])

    def test_what_the_escape_did_not_close_is_refused(self):
        self.screen = QUESTION
        out = self.start(session())
        self.assertEqual(out["reason"], "something is still open on its screen")
        self.assertEqual(self.typed(), [["tmux", "send-keys", "-t", "%168", "Escape"]])

    def test_a_pane_that_is_not_the_sessions_is_refused(self):
        jump.tmux_target = lambda pid, proc="/proc": "other:@1.%7"
        self.assertFalse(self.start(session())["ok"])
        self.assertEqual(self.ran, [])

    def test_no_link_in_time_says_what_was_typed(self):
        out = self.start(session())
        self.assertFalse(out["ok"])
        self.assertIn("/rc chienvert-france-boss", out["reason"])


if __name__ == "__main__":
    unittest.main()
