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
            "flag": None, "updatedAt": 0, "branch": "", "sessionId": name,
            "boss": False, "team": []}
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


class Teams(unittest.TestCase):
    """A boss leads its block, and the team it dispatches to follows."""

    def roster(self, members):
        real = fleet.sessions
        fleet.sessions = lambda cfg=None: members
        try:
            return fleet.roster()
        finally:
            fleet.sessions = real

    def test_the_boss_leads_whatever_the_activity(self):
        # Everyone else is busier and more recent; he still goes first.
        blocks = self.roster([
            session("Rosalie", project="pmd", status="busy", updatedAt=99),
            session("Lennart", project="pmd", boss=True,
                    team=["Rosalie", "Kasper"]),
            session("Kasper", project="pmd", status="busy", updatedAt=98),
        ])
        self.assertEqual([m["name"] for m in blocks[0]["members"]],
                         ["Lennart", "Rosalie", "Kasper"])

    def test_a_worker_knows_who_it_reports_to(self):
        blocks = self.roster([
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
            session("Rosalie", project="pmd"),
            session("Vera", project="maple"),
        ])
        by_name = {m["name"]: m for b in blocks for m in b["members"]}
        self.assertEqual(by_name["Rosalie"]["reportsTo"], "Lennart")
        self.assertEqual(by_name["Vera"]["reportsTo"], "")

    def test_a_worker_in_another_project_still_knows(self):
        # Workers are meant to sit in their own projects. It cannot be nested
        # under a block it is not in, but it can still say who sent it.
        blocks = self.roster([
            session("Lennart", project="pmd", boss=True, team=["Vera"]),
            session("Vera", project="maple"),
        ])
        by_name = {m["name"]: m for b in blocks for m in b["members"]}
        self.assertEqual(by_name["Vera"]["reportsTo"], "Lennart")

    def test_someone_the_boss_never_messaged_is_not_on_the_team(self):
        blocks = self.roster([
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
            session("Kasper", project="pmd", status="busy"),
        ])
        by_name = {m["name"]: m for b in blocks for m in b["members"]}
        self.assertEqual(by_name["Kasper"]["reportsTo"], "")


class TwoBosses(unittest.TestCase):
    """Teams read from real message traffic, which is noisier than a chart."""

    def roster(self, members):
        real = fleet.sessions
        fleet.sessions = lambda cfg=None: members
        try:
            return fleet.roster()
        finally:
            fleet.sessions = real

    def by_name(self, blocks):
        return {m["name"]: m for b in blocks for m in b["members"]}

    def test_a_boss_reports_to_nobody(self):
        # Two bosses message each other. One message is not a chain of
        # command, and marking one of them as the other's worker inverts
        # what the page is for.
        got = self.by_name(self.roster([
            session("Anton", project="lumen", boss=True, team=["Kian", "Lennart"]),
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
            session("Kian", project="lumen"),
            session("Rosalie", project="pmd"),
        ]))
        self.assertEqual(got["Lennart"]["reportsTo"], "")
        self.assertEqual(got["Kian"]["reportsTo"], "Anton")
        self.assertEqual(got["Anton"]["team"], ["Kian"])

    def test_a_worker_that_has_been_retired_leaves_the_team(self):
        # A boss retires workers as the work finishes. The page is about who
        # is running now, so a name with no session behind it is dropped.
        got = self.by_name(self.roster([
            session("Anton", project="lumen", boss=True, team=["Kian", "Ines"]),
            session("Kian", project="lumen"),
        ]))
        self.assertEqual(got["Anton"]["team"], ["Kian"])
