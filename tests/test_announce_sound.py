"""The page's two sounds, checked against the real `announce()` in index.html.

The header already counts a blocked session with waiting and stuck -- "a session
that wrote down what it is blocked on is asking". `announce()` used to disagree
and key the sound off `m.flag` alone, so a session reporting a blocker through
`team-line --n 1` finished its turn as `ready` and played the tick: the sound the
README defines as "something arrived, and it is not asking you for anything".
A real blocker went unheard that way on 2026-09-22.

The JS is extracted from index.html rather than copied here, so the test moves
with the page instead of quietly guarding a stale duplicate.
"""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"

HARNESS = """
let CHIME = true, WAITING = null, READY = null, sounds = [];
function ring(){ sounds.push("ring"); }
function tick(){ sounds.push("tick"); }
%s
function poll(rows){ sounds = []; announce(rows); return sounds.join(",") || "silence"; }
const M = (sid, flag, blocked) => ({key: sid, flag, blocked});
const cases = %s;
const out = [];
for (const [members, want] of cases) {
  // arrived() is false against a null baseline, so establish one per case and
  // let the members land as a fresh arrival.
  WAITING = new Set(); READY = new Set();
  poll([]);
  out.push(poll(members.map(m => M(m[0], m[1], m[2]))));
}
console.log(out.join("|"));
"""


def _announce_js():
    src = PAGE.read_text()
    start = src.index("function arrived(now, before)")
    end = src.index("function drawSound()")
    return src[start:end]


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class AnnounceSound(unittest.TestCase):
    # (members as [key, flag, blocked], expected sound)
    CASES = [
        # A blocker reported by team-line: the turn is over, but it is asking.
        ([["a", "ready", True]], "ring"),
        # Nothing wanted from you.
        ([["b", "ready", False]], "tick"),
        # AskUserQuestion is open.
        ([["c", "waiting", False]], "ring"),
        # A question outranks a finished turn in the same poll.
        ([["d", "ready", True], ["e", "ready", False]], "ring"),
        # Still working.
        ([["f", "busy", False]], "silence"),
    ]

    def test_blocked_rings_and_plain_finish_ticks(self):
        import json
        script = HARNESS % (_announce_js(), json.dumps(self.CASES))
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = proc.stdout.strip().split("|")
        want = [w for _, w in self.CASES]
        self.assertEqual(got, want)


SEQUENCE = """
let CHIME = true, WAITING = null, READY = null, sounds = [];
function ring(){ sounds.push("ring"); }
function tick(){ sounds.push("tick"); }
%s
const polls = %s;
const out = [];
for (const rows of polls) { sounds = []; announce(rows); out.push(sounds.join(",") || "silence"); }
console.log(out.join("|"));
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class CodexWaitRings(unittest.TestCase):
    """The flags the server really sends for a Codex row, through the real `announce()`."""

    def test_a_codex_wait_rings_once_and_rings_again_for_the_next_one(self):
        import json
        import sys
        sys.path.insert(0, str(ROOT / "tests"))
        import test_flags
        ask = test_flags.CodexRings.ASK
        row = lambda **o: test_flags.session("c", **o)
        base = test_flags.Base()
        base.setUp()
        self.addCleanup(base.doCleanups)
        polls = [
            [row(status="busy", quietFor=0.1)],          # page opened, working
            [row(status="busy", quietFor=0.1)],
            [row(status="waiting", asking=ask)],         # escalates: rings
            [row(status="waiting", asking=ask)],         # same wait: silent
            [row(status="waiting", asking=ask)],
            [row(status="busy", quietFor=0.1)],          # approved
            [row(status="waiting", asking=ask)],         # a new wait: rings
        ]
        sent = []
        for sessions in polls:
            fleet_flags = base.roster(*sessions, provider=test_flags.Fake(sessions, test_flags.CodexRings.CODEX))["flags"]
            sent.append([{"key": f["key"], "flag": f["flag"], "blocked": f["blocked"]} for f in fleet_flags])
        script = SEQUENCE % (_announce_js(), json.dumps(sent))
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().split("|"),
                         ["silence", "silence", "ring", "silence", "silence", "silence", "ring"])

    def test_a_codex_row_that_is_only_busy_or_idle_never_makes_a_sound(self):
        import json
        import sys
        sys.path.insert(0, str(ROOT / "tests"))
        import test_flags
        base = test_flags.Base()
        base.setUp()
        self.addCleanup(base.doCleanups)
        polls = [[test_flags.session("c", status=s, **q)] for s, q in
                 (("idle", {}), ("busy", {"quietFor": 0.1}), ("idle", {}), ("busy", {"quietFor": 0.1}))]
        sent = []
        for sessions in polls:
            rows = base.roster(*sessions, provider=test_flags.Fake(sessions, test_flags.CodexRings.CODEX))["flags"]
            sent.append([{"key": f["key"], "flag": f["flag"], "blocked": f["blocked"]} for f in rows])
        proc = subprocess.run(["node", "-e", SEQUENCE % (_announce_js(), json.dumps(sent))],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # A finished Codex turn may tick (ready); it never rings.
        self.assertNotIn("ring", proc.stdout)


if __name__ == "__main__":
    unittest.main()
