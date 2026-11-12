"""Where the "🔨 Name: task" lines sit on a track card, checked against the real
`doneWhenOf()` in index.html (the JS is extracted, as in test_announce_sound.py).

The rows come from the server worked, waiting, planned, done (boss-track/01,
Thierry's "active first"). The lines for workers on no row (`track.elsewhere`,
boss-track/04) used to follow every row, so on a card with seven planned and five
done rows a hammer sat below twelve rows. They now sit right after the worked
rows, so every hammer is together on top (boss-track/13).
"""
import json
import pathlib
import shutil
import subprocess
import unittest

PAGE = pathlib.Path(__file__).resolve().parent.parent / "index.html"

HARNESS = """
const localStorage = {getItem: () => null, setItem: () => {}};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const known = (t, k) => Object.prototype.hasOwnProperty.call(t, k) ? t[k] : "";
%s
const cards = %s;
const out = cards.map(c => {
  const html = doneWhenOf(c);
  return {html};
});
console.log(JSON.stringify(out));
"""


def _js():
    src = PAGE.read_text()
    return src[src.index("const SIGN ="):src.index("function notesLinkOf")]


def row(text, state):
    return {"text": text, "state": state, "awaiting_tick": False, "tickets": []}


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class HammersOnTop(unittest.TestCase):
    def draw(self, *cards):
        run = subprocess.run(["node", "-e", HARNESS % (_js(), json.dumps(list(cards)))],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def order(self, card):
        """The text of each line in the order the card shows them."""
        html = self.draw(card)[0]["html"]
        import re
        return re.findall(r"(?:<span class=\"sign\">[^<]*</span> ([^<]*?)(?:</button>|<br>|</span>))", html)

    def test_an_elsewhere_hammer_comes_after_the_worked_rows_and_before_the_rest(self):
        card = {"project": "p", "track": {
            "rows": [row("w1", "worked"), row("w2", "worked"), row("wait", "waiting"),
                     row("plan", "planned"), row("fin", "done")],
            "elsewhere": [{"name": "Anika", "task": "the audit"}]}}
        self.assertEqual(self.order(card), ["w1", "w2", "Anika: the audit", "wait", "plan", "fin"])

    def test_with_no_worked_row_the_hammer_is_first(self):
        card = {"project": "p", "track": {
            "rows": [row("wait", "waiting"), row("plan", "planned"), row("fin", "done")],
            "elsewhere": [{"name": "Anika", "task": "t"}]}}
        self.assertEqual(self.order(card), ["Anika: t", "wait", "plan", "fin"])

    def test_several_elsewhere_hammers_stay_together(self):
        card = {"project": "p", "track": {
            "rows": [row("w1", "worked"), row("plan", "planned")],
            "elsewhere": [{"name": "A", "task": "a"}, {"name": "B", "task": "b"}]}}
        self.assertEqual(self.order(card), ["w1", "A: a", "B: b", "plan"])

    def test_the_elsewhere_lines_are_not_clickable_and_rows_keep_their_button(self):
        card = {"project": "p", "track": {
            "rows": [row("w1", "worked"), row("plan", "planned")],
            "elsewhere": [{"name": "A", "task": "a"}]}}
        html = self.draw(card)[0]["html"]
        self.assertEqual(html.count("<button"), 2)
        self.assertEqual(html.count('data-row="'), 2)

    def test_no_rows_still_lists_the_hammers(self):
        card = {"project": "p", "track": {"rows": [], "elsewhere": [{"name": "A", "task": "a"}]}}
        self.assertEqual(self.order(card), ["A: a"])

    def test_no_elsewhere_leaves_the_rows_as_they_were(self):
        card = {"project": "p", "track": {"rows": [row("w1", "worked"), row("plan", "planned")]}}
        self.assertEqual(self.order(card), ["w1", "plan"])
        self.assertEqual(self.draw(card)[0]["html"].count("<li"), 2)

    def test_markup_in_a_name_or_task_builds_no_element(self):
        card = {"project": "p", "track": {"rows": [row("plan", "planned")],
                "elsewhere": [{"name": "<b>x</b>", "task": "\"><i>"}]}}
        html = self.draw(card)[0]["html"]
        self.assertNotIn("<b>", html)
        self.assertNotIn("<i>", html)


if __name__ == "__main__":
    unittest.main()
