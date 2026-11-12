"""The reload decision in index.html, run under node with the page's own `arrived`, `announce`
and `staleAndFree` lifted out of the script and everything else stubbed. No browser, no server."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")


def lift(name):
    m = re.search(rf"^(?:async )?function {name}\(.*?^}}\n", HTML, re.S | re.M)
    assert m, name
    return m.group(0)


HARNESS = """
let WAITING = null, READY = null, CHIME = true, SAVING = false, editing = false, now = 0;
let rang = [];
const ring = () => rang.push("ring"), tick = () => rang.push("tick");
const busyWithUser = () => false;
const document = {getElementById: () => ({value: ""}), activeElement: null};
const BUILD = "old", CHIME_MS = 2500;
let ANNOUNCED_AT = 0;
%s
// What load() does at its end, with the same two lines it runs.
function poll(flags, build, t) {
  now = t;
  if (announce(flags)) ANNOUNCED_AT = now;
  return staleAndFree(build) && now - ANNOUNCED_AT > CHIME_MS;
}
const waiting = k => ({key: k, flag: "waiting"});
const out = [];
out.push(poll([], "old", 10000));                       // baseline
out.push(poll([waiting("a")], "new", 13000));           // new build and a first ask
out.push(poll([waiting("a")], "new", 16000));           // 3 s later, nothing new
out.push(poll([waiting("a"), waiting("b")], "new", 19000)); // a second ask: hold again
out.push(poll([waiting("a"), waiting("b")], "new", 22000));
out.push(poll([waiting("a"), waiting("b")], "old", 25000)); // same build: never
console.log(JSON.stringify({out, rang}));
""" % "\n".join(lift(n) for n in ("arrived", "announce", "staleAndFree"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ReloadWaitsForTheChime(unittest.TestCase):
    def test_the_poll_that_brings_a_waiting_session_does_not_reload(self):
        got = json.loads(subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True,
                                        check=True, timeout=30).stdout)
        self.assertEqual(got["out"], [False, False, True, False, True, False])
        self.assertEqual(got["rang"], ["ring", "ring"])


if __name__ == "__main__":
    unittest.main()
