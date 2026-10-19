import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
from providers import claude

CFG = Path("/home/alice/.claude")
SCRIPT = "bash /home/alice/.claude/routines/nightly-report.sh"


class RoutineOf(unittest.TestCase):
    def test_a_timer_run_is_named_after_its_script(self):
        got = claude.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=[SCRIPT])
        self.assertEqual(got, "nightly-report")

    def test_the_script_may_be_further_up_the_tree(self):
        # A routine that pipes its output runs under a shell of its own.
        got = claude.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=["/bin/sh -c claude -p ... | tee log", SCRIPT])
        self.assertEqual(got, "nightly-report")

    def test_a_terminal_session_is_never_a_routine(self):
        # `cli` settles it, whatever the ancestry says -- a routine's own
        # shell could well be the thing you started this terminal from.
        got = claude.routine_of({"entrypoint": "cli", "pid": 1}, CFG,
                               ancestry=[SCRIPT])
        self.assertEqual(got, "")

    def test_headless_without_a_routine_script_is_not_claimed(self):
        # `claude -p` typed by hand is headless too. Calling it a routine
        # would be a guess, and it would go missing from its own project.
        got = claude.routine_of({"entrypoint": "sdk-cli", "pid": 1}, CFG,
                               ancestry=["bash /home/alice/bin/something.sh"])
        self.assertEqual(got, "")


def session(name, routine="", project=None, **kw):
    # The fields the page reads off a row; `roster()` now makes tiles from them.
    base = {"name": name, "routine": routine, "project": project, "status": "idle",
            "flag": None, "updatedAt": 0, "branch": "", "key": name, "id": name,
            "boss": False, "team": [], "blocked": False, "n": 0,
            "provider": "claude", "title": "", "did": "", "ask": "", "prompt": "",
            "cwd": f"/home/alice/Projects/{project}" if project else "", "canJump": False, "waitingFor": "", "quietFor": None,
            "toolFor": None, "movement": None, "moving": False, "asking": None,
            "failure": None, "lastTool": None, "procsUnknown": False, "silentFor": None,
            "idleFor": None, "unread": False, "pinned": False, "said": ""}
    base.update(kw)
    return base


class Seen(unittest.TestCase):
    """The sessions through `members()`, the order the overview is made from,
    and through `roster()` for what the page and the chime are given."""

    def run_with(self, members, fn):
        real = fleet.sessions
        fleet.sessions = lambda providers=None: members
        try:
            return fn()
        finally:
            fleet.sessions = real

    def members(self, members):
        return self.run_with(members, fleet.members)

    def roster(self, members):
        return self.run_with(members, fleet.roster)

    def names(self, members):
        return [m["name"] for m in self.members(members)]


class Grouping(Seen):
    def test_every_routine_comes_after_the_projects_and_none_is_in_a_column(self):
        # They run from ~, so before this they were scattered through
        # `No project` -- the pile that means "assign me", which is the one
        # thing a routine never needs.
        rows = [
            session("Ansgar", routine="nightly-report"),
            session("Bruno", routine="disk-check"),
            session("Vera", project="maple"),
        ]
        self.assertEqual(self.names(rows), ["Vera", "Ansgar", "Bruno"])
        got = self.roster(rows)
        self.assertEqual([c["name"] for c in got["columns"]], ["Maple"])
        self.assertEqual(sorted(f["name"] for f in got["flags"]), ["Ansgar", "Bruno", "Vera"])

    def test_a_project_of_the_same_name_is_not_swallowed(self):
        got = self.roster([
            session("Ansgar", routine="nightly-report"),
            session("Vera", project="Routines"),
        ])
        (column,) = got["columns"]
        self.assertEqual((column["name"], [t["name"] for t in column["sessions"]]), ("Routines", ["Vera"]))
        self.assertEqual(sorted(f["name"] for f in got["flags"]), ["Ansgar", "Vera"])

    def test_routines_sit_below_even_no_project(self):
        # `No project` is asking you for something. A routine is asking for
        # nothing and will be gone in a few minutes.
        self.assertEqual(self.names([
            session("Ansgar", routine="nightly-report", status="busy"),
            session("Nemo"),
            session("Vera", project="maple"),
        ]), ["Vera", "Nemo", "Ansgar"])


class Teams(Seen):
    """A boss leads its project, and the team it dispatches to follows."""

    def test_the_boss_leads_whatever_the_activity(self):
        # Everyone else is busier and more recent; he still goes first.
        self.assertEqual(self.names([
            session("Rosalie", project="pmd", status="busy", updatedAt=99),
            session("Lennart", project="pmd", boss=True,
                    team=["Rosalie", "Kasper"]),
            session("Kasper", project="pmd", status="busy", updatedAt=98),
        ]), ["Lennart", "Rosalie", "Kasper"])

    def test_the_team_follows_the_boss_ahead_of_a_busier_stranger(self):
        self.assertEqual(self.names([
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
            session("Kasper", project="pmd", status="busy", updatedAt=99),
            session("Rosalie", project="pmd"),
        ]), ["Lennart", "Rosalie", "Kasper"])

    def test_someone_the_boss_never_messaged_is_not_on_the_team(self):
        self.assertEqual(self.names([
            session("Kasper", project="pmd", status="busy", updatedAt=99),
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
        ]), ["Lennart", "Kasper"])

    def test_a_worker_in_another_project_stays_in_its_own(self):
        # Workers are meant to sit in their own projects. It cannot be nested
        # under a project it is not in.
        rows = [
            session("Lennart", project="pmd", boss=True, team=["Vera"]),
            session("Vera", project="maple"),
        ]
        self.assertEqual(sorted(self.names(rows)), ["Lennart", "Vera"])
        self.assertEqual(sorted(c["name"] for c in self.roster(rows)["columns"]), ["Maple", "Pmd"])


class TwoBosses(Seen):
    """Teams read from real message traffic, which is noisier than a chart."""

    def by_name(self, members):
        return {m["name"]: m for m in self.members(members)}

    def test_a_boss_is_on_nobodys_team(self):
        # Two bosses message each other. One message is not a chain of
        # command, and marking one of them as the other's worker inverts
        # what the page is for.
        got = self.by_name([
            session("Anton", project="lumen", boss=True, team=["Kian", "Lennart"]),
            session("Lennart", project="pmd", boss=True, team=["Rosalie"]),
            session("Kian", project="lumen"),
            session("Rosalie", project="pmd"),
        ])
        self.assertEqual(got["Anton"]["team"], ["Kian"])
        self.assertEqual(got["Lennart"]["team"], ["Rosalie"])

    def test_a_worker_that_has_been_retired_leaves_the_team(self):
        # A boss retires workers as the work finishes. The page is about who
        # is running now, so a name with no session behind it is dropped.
        got = self.by_name([
            session("Anton", project="lumen", boss=True, team=["Kian", "Ines"]),
            session("Kian", project="lumen"),
        ])
        self.assertEqual(got["Anton"]["team"], ["Kian"])


if __name__ == "__main__":
    unittest.main()
