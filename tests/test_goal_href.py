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
const location = {hostname: "127.0.0.1"};      // the laptop: the only page that links
%s
%s
console.log(goalLinkOf({track: {goal: {url: %s, why: ""}}}));
"""

ATTR = '"><img src=x onerror=alert(1)> x="'        # breaks out of a quoted attribute, if one is not escaped


def _page_js():
    src = PAGE.read_text()
    start = src.index("const esc = ")
    esc = src[start:src.index("\n", start)]
    start = src.index("const ON_THE_LAPTOP")
    return esc, src[start:src.index("\n}\n", start) + 2]


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
    def link(self, url):
        proc = subprocess.run(["node", "-e", HARNESS % (*_page_js(), json.dumps(url))],
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
                self.assertEqual(got.elements[0][1]["href"], url)
                self.assertEqual(got.text, "goal ↗")


if __name__ == "__main__":
    unittest.main()
