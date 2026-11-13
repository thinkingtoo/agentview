"""Every caller of the project action says Fold into and calls /api/fold; "merge" is a pull request's word.

No browser: the page's source and the README are read as text (the card menu's words
as drawn are checked by tests/ui_smoke.py, on t-compute).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server

PAGE = (ROOT / "index.html").read_text()


class FoldNames(unittest.TestCase):
    def test_the_page_calls_fold_and_never_the_old_route(self):
        self.assertIn('"/api/fold"', PAGE)
        self.assertNotIn("/api/merge", PAGE)

    def test_the_card_menu_and_the_form_say_fold_into(self):
        self.assertIn(">Fold into…<", PAGE)
        self.assertIn("fold all of it into", PAGE)
        self.assertNotRegex(PAGE, r">merge…<|merge all of it|aria-label=\"merge into\"|<button data-act=\"go\">merge<")

    def test_the_undo_line_still_reads_includes_x_undo(self):
        self.assertIn("includes ${esc(m.name)}", PAGE)
        self.assertIn('data-act="unfold"', PAGE)
        self.assertNotIn("unmerge", PAGE)

    def test_both_routes_are_in_the_route_table(self):
        self.assertIn("fold", server.Handler.ROUTES)
        self.assertIn("merge", server.Handler.ROUTES)      # an open page of the old code

    def test_no_other_caller_in_the_repo_posts_the_old_route(self):
        owners = {"tests/test_by_hand.py", "tests/test_fold_names.py", "server.py", "README.md"}
        for f in ROOT.rglob("*"):
            rel = f.relative_to(ROOT).as_posix()
            if (not f.is_file() or f.suffix not in (".py", ".html", ".sh", ".md", "")
                    or rel.startswith((".git/", ".scratch/", "docs/", "handoff")) or rel in owners):
                continue
            self.assertNotIn("/api/merge", f.read_text(errors="ignore"), rel)

    def test_the_readme_says_fold_into_for_the_project_action(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("**Fold into…**", text)
        self.assertNotIn("**merge…**", text)
        self.assertNotRegex(text, r"A merge is taken back|Merge and move of a whole project")


if __name__ == "__main__":
    unittest.main()
