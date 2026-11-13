"""The page's side of the merge desk's ring, checked against the real `deskRing()` in index.html.

The server decides when the ring is due (`deskring.py`); the page plays it as the ring of a session that
needs you, unless the chime is muted, and keeps its words for the Merges button's tooltip. The JS is
extracted from index.html so that the test moves with the page.
"""
import pathlib
import shutil
import subprocess
import unittest

PAGE = pathlib.Path(__file__).resolve().parent.parent / "index.html"

HARNESS = """
let CHIME = %s, DESK_RUNG = "", sounds = [];
function ring(){ sounds.push("ring"); }
%s
const got = [deskRing(%s), sounds.join(",") || "silence", DESK_RUNG];
console.log(JSON.stringify(got));
"""


def run(chime, arg):
    src = PAGE.read_text()
    start = src.index("function deskRing(text)")
    end = src.index("function drawSound()")
    out = subprocess.run(["node", "-e", HARNESS % (chime, src[start:end], arg)],
                         capture_output=True, text=True, check=True).stdout
    import json
    return json.loads(out)


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class DeskRing(unittest.TestCase):
    def test_a_due_ring_plays_the_ring_and_keeps_its_words(self):
        self.assertEqual(run("true", '"The merge desk has waited"'), [True, "ring", "The merge desk has waited"])

    def test_no_ring_due_is_silence(self):
        for arg in ("null", '""', "undefined"):
            self.assertEqual(run("true", arg), [False, "silence", ""])

    def test_a_muted_chime_stays_silent(self):
        self.assertEqual(run("false", '"The merge desk"'), [False, "silence", "The merge desk"])

    def test_the_button_is_beside_the_pastes_button_and_lights_none_of_the_counts(self):
        src = PAGE.read_text()
        self.assertIn("${buttons}${pastes}${merges}${down}", src)
        self.assertIn('MERGES ? `', src)        # 0 hides it
        self.assertNotIn('data-count="merges"', src)


if __name__ == "__main__":
    unittest.main()
