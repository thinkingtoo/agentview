"""The "goal ↗" link's href, checked against the real `goalLinkOf()` in index.html.

The url comes from the hub's port and sheaf's roots (goal_page.py), whose paths
are quote()d, so markup in it is unlikely; but the page puts it in a quoted
attribute, and only `esc()` keeps a quote there from ending the attribute and
building whatever follows. Ticket overview-build/28 pins that: the link parses
back to one <a> whose href is the url exactly as sent.

The JS is extracted from index.html rather than copied here, so the test moves
with the page instead of quietly guarding a stale duplicate.
"""
import html.parser
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"

HARNESS = """
const location = {hostname: %s};
%s
console.log(goalLinkOf({track: {goal: {url: %s, door: %s, why: ""}}}));
"""
LAPTOP, PHONE = "127.0.0.1", "laptop.tailnet.ts.net"
DOOR = "https://laptop.tailnet.ts.net:8446/goals/kettle.md"

ATTR = '"><img src=x onerror=alert(1)> x="'        # breaks out of a quoted attribute, if one is not escaped


def _line(src, opening):
    start = src.index(opening)
    return src[start:src.index("\n", start)]


def _function(src, opening):
    start = src.index(opening)
    return src[start:src.index("\n}\n", start) + 2]


def _page_js():
    """`esc`, `ON_THE_LAPTOP`, `onTheHub` and `goalLinkOf`, as the page has them."""
    src = PAGE.read_text()
    return "\n".join((_line(src, "const esc = "), _line(src, "const ON_THE_LAPTOP"),
                      _function(src, "function onTheHub(url)"), _function(src, "function onTheDoor(url)"),
                      _function(src, "function goalLinkOf(c)")))


class Parsed(html.parser.HTMLParser):
    """Every element the markup builds, as (tag, attrs), and its text."""

    def __init__(self):
        super().__init__()
        self.elements, self.text = [], ""

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text += data


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's JS")
class GoalHref(unittest.TestCase):
    def link(self, url, host=LAPTOP, door=None):
        proc = subprocess.run(["node", "-e", HARNESS % (json.dumps(host), _page_js(), json.dumps(url), json.dumps(door))],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = Parsed()
        parsed.feed(proc.stdout.strip())
        parsed.close()
        return parsed

    def test_a_quote_or_markup_in_the_goal_url_stays_in_the_href_and_builds_nothing(self):
        for url in ("http://127.0.0.1:7417/goals/kettle.md" + ATTR,
                    "http://127.0.0.1:7417/goals/kettle.md?a=1&lt;b&quot;c"):
            with self.subTest(url=url):
                got = self.link(url)
                self.assertEqual([tag for tag, _ in got.elements], ["a"], got.elements)
                self.assertEqual(set(got.elements[0][1]), {"class", "href", "target", "rel", "title"})
                self.assertEqual(got.elements[0][1]["href"], url)
                self.assertEqual(got.text, "goal ↗")

    def test_a_url_whose_host_is_not_127_0_0_1_or_that_does_not_parse_is_not_linked(self):
        # Ticket overview-build/33: the guard checked a prefix. In the first two
        # urls what precedes `@` is userinfo and the host is evil.example; the
        # last two parse to no url at all.
        for url in ("http://127.0.0.1:x@evil.example/p.md", "http://127.0.0.1:7417@evil.example/p.md",
                    "http://127.0.0.1:7417.evil.example/p.md", "http://127.0.0.1:[/p.md"):
            with self.subTest(url=url):
                got = self.link(url)
                self.assertEqual([tag for tag, _ in got.elements], ["span"], got.elements)
                self.assertEqual(got.text, "no goal page")


if __name__ == "__main__":
    unittest.main()

    def test_off_the_laptop_the_link_is_the_door_on_the_page_s_own_host(self):
        got = self.link("http://127.0.0.1:7417/goals/kettle.md", host=PHONE, door=DOOR)
        self.assertEqual([tag for tag, _ in got.elements], ["a"])
        self.assertEqual(got.elements[0][1]["href"], DOOR)

    def test_a_door_on_another_host_or_without_https_links_nothing(self):
        for door in ("https://elsewhere.example:8446/goals/kettle.md", "http://laptop.tailnet.ts.net:8446/goals/kettle.md",
                     "https://x@laptop.tailnet.ts.net:8446/goals/kettle.md", None):
            with self.subTest(door=door):
                got = self.link("http://127.0.0.1:7417/goals/kettle.md", host=PHONE, door=door)
                self.assertEqual([tag for tag, _ in got.elements], ["span"])
                self.assertIn("goal on the laptop", got.text)

    def test_on_the_laptop_the_hub_link_stays_even_with_a_door(self):
        got = self.link("http://127.0.0.1:7417/goals/kettle.md", door=DOOR)
        self.assertEqual(got.elements[0][1]["href"], "http://127.0.0.1:7417/goals/kettle.md")
