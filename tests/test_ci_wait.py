"""A session waiting on CI (ticket 22): its turn is over and the latest Actions
run on its branch, for the commit its own checkout is at, is queued or running.
The tile says so with an ETA, the card waits, nothing rings.

Through `roster()` with fake providers. `fleet.CI_STATE` (the vendored
claude-boss `ci_state`) and `fleet.CI_HEAD` (where the session's checkout is)
are replaced, so nothing here reaches GitHub or a real repository. Names,
repositories and commits are invented.
"""
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import projects
from test_columns import Base, session

SHA = "a" * 40


def ago(minutes):
    return int(time.time() * 1000 - minutes * 60000)


def run(status="in_progress", head_sha=SHA, **over):
    out = {"status": status, "conclusion": None, "queued_for_s": None, "running_for_s": None,
           "eta_s": None, "eta_excludes_queue": False,
           "run_url": "https://github.com/maple/notes/actions/runs/1", "error": None,
           "head_sha": head_sha}
    out.update(over)
    return out


def resting(**over):
    return session("a", status="idle", updatedAt=ago(5), branch="feature/notes", **over)


class CiWait(Base):
    def setUp(self):
        super().setUp()
        self.asked = []
        self.answer = run(running_for_s=12 * 60, eta_s=8 * 60)
        self.head = ("github.com/maple/notes", SHA)

        def state(repo, branch):
            self.asked.append((repo, branch))
            return self.answer
        for name, value in (("CI_STATE", state), ("CI_HEAD", lambda cwd: self.head)):
            self.addCleanup(setattr, fleet, name, getattr(fleet, name))
            setattr(fleet, name, value)

    def test_a_resting_session_whose_run_is_going_waits_on_ci_with_an_eta(self):
        got = self.roster(resting())
        tile, column = got["columns"][0]["sessions"][0], got["columns"][0]
        self.assertEqual((tile["waiting"], tile["moving"], tile["activity"]), (True, False, "waiting"))
        self.assertEqual(tile["movement"]["text"], "waiting on CI: running 12 min, about 8 min left")
        self.assertEqual(tile["ci"]["url"], "https://github.com/maple/notes/actions/runs/1")
        self.assertEqual(column["state"], "waiting")
        self.assertEqual(self.asked, [("github.com/maple/notes", "feature/notes")])
        self.assertEqual(got["counts"]["moving"], 0)

    def test_a_queued_run_says_how_long_it_has_queued_and_that_the_eta_leaves_the_queue_out(self):
        self.answer = run("queued", queued_for_s=5 * 60, eta_s=20 * 60, eta_excludes_queue=True)
        tile = self.tile(resting())
        self.assertEqual(tile["movement"]["text"], "waiting on CI: queued 5 min, then about 20 min")

    def test_no_eta_says_no_eta(self):
        self.answer = run(running_for_s=3 * 60)
        self.assertEqual(self.tile(resting())["movement"]["text"], "waiting on CI: running 3 min")

    def test_a_run_for_another_commit_is_not_this_sessions_wait(self):
        for head_sha in ("b" * 40, None):
            with self.subTest(head_sha=head_sha):
                self.answer = run(head_sha=head_sha, running_for_s=60)
                tile = self.tile(resting())
                self.assertEqual((tile["waiting"], tile["ci"]), (False, None))

    def test_a_finished_or_unknown_run_is_no_wait(self):
        for status in ("completed", "unknown"):
            with self.subTest(status=status):
                self.answer = run(status)
                self.assertFalse(self.tile(resting())["waiting"])

    def test_a_session_at_work_or_stuck_is_not_asked(self):
        self.tile(session("a", status="busy", quietFor=0.1, branch="feature/notes"))
        self.tile(session("a", status="waiting", waitingFor="input needed", updatedAt=ago(2),
                          branch="feature/notes", asking={"kind": "question", "questions": []}))
        self.assertEqual(self.asked, [])

    def test_a_session_with_no_branch_or_no_github_remote_is_not_asked(self):
        self.tile(session("a", status="idle", updatedAt=ago(5)))
        self.head = ("gitlab.example.com/maple/notes", SHA)
        self.tile(resting())
        self.head = None
        self.tile(resting())
        self.assertEqual(self.asked, [])

    def test_a_session_resting_for_hours_is_not_asked(self):
        self.tile(session("a", status="idle", updatedAt=ago(5 * 60), quietFor=5 * 60.0,
                          branch="feature/notes"))
        self.assertEqual(self.asked, [])

    def test_a_session_waiting_on_ci_is_never_a_pill(self):
        self.config = {"finished_after_minutes": 1}
        got = self.roster(resting())["columns"][0]
        self.assertEqual(([t["key"] for t in got["sessions"]], got["pills"]), (["fake:a"], []))


class HeadOf(unittest.TestCase):
    """Where a checkout is, read from its `.git` files: never `git`, never a
    file that is not a regular one."""

    def folder(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def repo(self):
        root = self.folder() / "notes"
        root.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                        capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("remote", "add", "origin", "git@github.com:maple/notes.git")
        (root / "a.txt").write_text("a")
        git("add", "a.txt")
        git("-c", "user.email=m@example.com", "-c", "user.name=m", "commit", "-qm", "a")
        return root, git

    def test_a_checkout_says_its_remote_and_commit(self):
        root, git = self.repo()
        self.assertEqual(projects.head_of(str(root)), ("github.com/maple/notes", git("rev-parse", "HEAD")))

    def test_a_worktree_says_its_own_commit(self):
        root, git = self.repo()
        wt = root.parent / "notes-wt"
        git("worktree", "add", "-q", "-b", "other", str(wt))
        (wt / "b.txt").write_text("b")
        subprocess.run(["git", "-C", str(wt), "add", "b.txt"], check=True)
        subprocess.run(["git", "-C", str(wt), "-c", "user.email=m@example.com", "-c", "user.name=m",
                        "commit", "-qm", "b"], check=True)
        own = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
        self.assertEqual(projects.head_of(str(wt)), ("github.com/maple/notes", own))

    def test_a_packed_ref_is_read(self):
        root, git = self.repo()
        sha = git("rev-parse", "HEAD")
        git("pack-refs", "--all")
        self.assertEqual(projects.head_of(str(root))[1], sha)

    def test_no_repository_or_no_remote_is_none(self):
        self.assertIsNone(projects.head_of(str(self.folder())))
        root, git = self.repo()
        git("remote", "remove", "origin")
        self.assertIsNone(projects.head_of(str(root)))


if __name__ == "__main__":
    unittest.main()
