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
import re
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
        return re.findall(r"(?:<span class=\"sign[^\"]*\"[^>]*>[^<]*</span> ([^<]*?)(?:</button>|<br>|</span>))", html)

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

    def test_the_live_shape_of_the_codex_down_card_has_its_hammer_first(self):
        """0 worked rows, 3 planned, 9 done, one elsewhere (2026-11-12, boss-track/16): the old
        page drew the hammer last, this one first."""
        card = {"project": "p", "track": {
            "rows": [row(f"p{i}", "planned") for i in range(3)] + [row(f"d{i}", "done") for i in range(9)],
            "elsewhere": [{"name": "Otilia", "task": "#29 edge cases"}]}}
        self.assertEqual(self.order(card)[0], "Otilia: #29 edge cases")
        self.assertEqual(len(self.order(card)), 13)


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class HammersSwing(unittest.TestCase):
    """A busy worker's hammer swings; any other is still (boss-track/17)."""
    draw = HammersOnTop.draw

    def swung(self, card):
        """`{line text: whether its sign carries swing}`, for every line of the card."""
        html = self.draw(card)[0]["html"]
        return {text: "swing" in cls.split() for cls, text in re.findall(
            r'<span class="(sign[^"]*)"[^>]*>[^<]*</span> ([^<]*?)(?:</button>|<br>|</span>)', html)}

    def test_a_busy_row_and_a_busy_elsewhere_entry_swing_and_the_rest_are_still(self):
        card = {"project": "p", "track": {
            "rows": [dict(row("busy row", "worked"), busy=True), dict(row("quiet row", "worked"), busy=False),
                     dict(row("asked", "waiting"), busy=False), row("plan", "planned"), row("fin", "done")],
            "elsewhere": [{"name": "A", "task": "a", "busy": True}, {"name": "B", "task": "b", "busy": False}]}}
        self.assertEqual(self.swung(card), {
            "busy row": True, "quiet row": False, "A: a": True, "B: b": False,
            "asked": False, "plan": False, "fin": False})

    def test_a_redrawn_hammer_carries_on_at_the_clock_phase_of_the_swing(self):
        card = {"project": "p", "track": {"rows": [dict(row("w", "worked"), busy=True)]}}
        delay = int(re.search(r'animation-delay:-(\d+)ms', self.draw(card)[0]["html"]).group(1))
        self.assertTrue(0 <= delay < 1200)
        self.assertIn("1200ms", PAGE.read_text())

    def test_a_roster_without_the_busy_field_swings_nothing(self):
        card = {"project": "p", "track": {"rows": [row("w", "worked")], "elsewhere": [{"name": "A", "task": "a"}]}}
        self.assertEqual(self.swung(card), {"w": False, "A: a": False})

    def test_the_waiting_row_never_swings_even_if_the_server_says_busy(self):
        card = {"project": "p", "track": {"rows": [dict(row("asked", "waiting"), busy=True)]}}
        self.assertEqual(self.swung(card), {"asked": False})

    def test_a_watching_row_and_entry_show_the_flask_and_rock_the_hammers_do_not(self):
        card = {"project": "p", "track": {
            "rows": [dict(row("w row", "worked"), busy=False, watching=True),
                     dict(row("b row", "worked"), busy=True, watching=True),      # swinging beats it
                     dict(row("q row", "worked"), busy=False, watching=False)],
            "elsewhere": [{"name": "A", "task": "a", "busy": False, "watching": True},
                          {"name": "B", "task": "b", "busy": False, "watching": False}]}}
        html = self.draw(card)[0]["html"]
        got = {text: (cls.split(), glyph) for cls, glyph, text in re.findall(
            r'<span class="(sign[^"]*)"[^>]*>([^<]*)</span> ([^<]*?)(?:</button>|<br>|</span>)', html)}
        self.assertEqual(got["w row"], (["sign", "rock"], "🧪"))
        self.assertEqual(got["A: a"], (["sign", "rock"], "🧪"))
        self.assertEqual(got["b row"], (["sign", "swing"], "🔨"))
        self.assertEqual(got["q row"], (["sign"], "🔨"))
        self.assertEqual(got["B: b"], (["sign"], "🔨"))

    def test_the_waiting_row_never_shows_the_flask(self):
        card = {"project": "p", "track": {"rows": [dict(row("asked", "waiting"), watching=True)]}}
        html = self.draw(card)[0]["html"]
        self.assertIn("⏸", html)
        self.assertNotIn("🧪", html)

    def test_the_rock_is_gated_on_motion_and_is_no_swing(self):
        css = PAGE.read_text()
        gate = css.index("@media (prefers-reduced-motion: no-preference)")
        self.assertIn(".sign.rock", css[gate:css.index("</style>", gate)])
        self.assertNotIn(".sign.rock", css[:gate])
        self.assertNotRegex(css[:gate], r"animation:[^;]*rock")
        # The left tilt of -9deg pulls a 1em glyph's corner 0.14em left: it must start that far right.
        rests = [float(x) for x in re.findall(r"translateX\(([\d.]+)em\)", re.search(r"@keyframes rock \{(.*?)\n", css).group(1))]
        self.assertTrue(rests and min(rests) >= 0.14, rests)
        self.assertNotEqual(re.search(r"@keyframes rock \{(.*?)\n", css).group(1),
                            re.search(r"@keyframes swing \{(.*?)\n", css).group(1))

    def test_the_stylesheet_swings_only_where_motion_is_welcome(self):
        css = PAGE.read_text()
        gate = css.index("@media (prefers-reduced-motion: no-preference)")
        self.assertIn(".sign.swing", css[gate:css.index("</style>", gate)])
        self.assertNotRegex(css[:gate], r"animation:[^;]*swing")
        self.assertNotIn(".sign.swing", css[:gate])


if __name__ == "__main__":
    unittest.main()
