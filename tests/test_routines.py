import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet

CFG = Path("/home/alice/.claude")
SCRIPT = "bash /home/alice/.claude/routines/nightly-report.sh"


class RoutineOf(unittest.TestCase):
    def test_a_timer_run_is_named_after_its_script(self):
        got = fleet.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=[SCRIPT])
        self.assertEqual(got, "nightly-report")

    def test_the_script_may_be_further_up_the_tree(self):
        # A routine that pipes its output runs under a shell of its own.
        got = fleet.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=["/bin/sh -c claude -p ... | tee log", SCRIPT])
        self.assertEqual(got, "nightly-report")

    def test_a_terminal_session_is_never_a_routine(self):
        # `cli` settles it, whatever the ancestry says -- a routine's own
        # shell could well be the thing you started this terminal from.
        got = fleet.routine_of({"entrypoint": "cli", "pid": 1}, CFG,
                               ancestry=[SCRIPT])
        self.assertEqual(got, "")

    def test_headless_without_a_routine_script_is_not_claimed(self):
        # `claude -p` typed by hand is headless too. Calling it a routine
        # would be a guess, and it would go missing from its own project.
        got = fleet.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=["bash /home/alice/bin/something.sh"])
        self.assertEqual(got, "")


def session(name, routine="", project=None, **kw):
    base = {"name": name, "routine": routine, "project": project, "status": "idle",
            "flag": None, "updatedAt": 0, "branch": "", "sessionId": name}
    base.update(kw)
    return base


class Grouping(unittest.TestCase):
    def roster(self, members):
        real = fleet.sessions
        fleet.sessions = lambda cfg=None: members
        try:
            return fleet.roster()
        finally:
            fleet.sessions = real

    def test_every_routine_lands_in_one_block_of_its_own(self):
        # They run from ~, so before this they were scattered through
        # `No project` -- the pile that means "assign me", which is the one
        # thing a routine never needs.
        blocks = self.roster([
            session("Ansgar", routine="nightly-report"),
            session("Bruno", routine="disk-check"),
            session("Vera", project="maple"),
        ])
        by_name = {b["project"]: b for b in blocks}
        self.assertEqual(sorted(by_name), ["Routines", "maple"])
        self.assertEqual([m["name"] for m in by_name["Routines"]["members"]],
                         ["Ansgar", "Bruno"])
        self.assertTrue(by_name["Routines"]["routines"])
        self.assertFalse(by_name["Routines"]["orphan"])

    def test_a_project_of_the_same_name_is_not_swallowed(self):
        blocks = self.roster([
            session("Ansgar", routine="nightly-report"),
            session("Vera", project="Routines"),
        ])
        routines = [b for b in blocks if b["routines"]]
        self.assertEqual(len(blocks), 2)
        self.assertEqual([m["name"] for m in routines[0]["members"]], ["Ansgar"])

    def test_routines_sit_below_even_no_project(self):
        # `No project` is asking you for something. A routine is asking for
        # nothing and will be gone in a few minutes.
        blocks = self.roster([
            session("Ansgar", routine="nightly-report", status="busy"),
            session("Nemo"),
            session("Vera", project="maple"),
        ])
        self.assertEqual([b["project"] for b in blocks],
                         ["maple", "No project", "Routines"])


if __name__ == "__main__":
    unittest.main()
