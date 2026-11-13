"""A track's rows: one per Done when line of its goal, each with its state
(done, worked, waiting, planned) and the tickets it names (ticket boss-track/01).

Everything goes through `roster()` with fake providers, like `test_context`.
Goal files, trackers, tickets and repositories are built in a temp dir;
nothing here reads the real `~/.claude/pm` or a real repository. Names and
texts are invented.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet
import lines
from test_projects import TrackFixtures, sess


JOB = dict(turnOver=True, bgTasks=[{"label": "watch", "since": 3.0}])   # a turn over, a job of its own open


class Fixtures(TrackFixtures):
    def setUp(self):
        super().setUp()
        self.loom = self.repo("loom")          # where the boss and its workers work

    def goal(self, *boxes, track="checkout"):
        body = "".join(f"- {b}\n" for b in boxes)
        (self.pm / f"{track}.goal.md").write_text(
            f"# Objective — {track}\n_Status: OPEN_\n\n## Outcome\nCustomers pay with a saved card.\n\n"
            f"## Done when\n{body}\n## Deliverables\n- [ ] not a criterion\n")

    def roster_of(self, *rows, track="checkout", heading="Roster"):
        """`pm/<track>.md` with a roster table of (name, task) rows."""
        table = "".join(f"| {name} | %31 | {task} |\n" for name, task in rows)
        (self.pm / f"{track}.md").write_text(
            f"# PM Tracker — {track}\n\n## {heading}\n| Name | Pane | Current task |\n|---|---|---|\n"
            f"{table}\n## Open blockers\n- 04:50 paste/12 was merged\n")

    def ticket(self, ref, status="ready-for-agent", blocked="None", title=None, repo=None, slug="a-ticket"):
        feature, number = ref.split("/")
        folder = (repo or self.loom) / ".scratch" / feature / "issues"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{number}-{slug}.md"
        path.write_text(f"# {number}: {title or 'Ticket ' + ref}\n\n**What to build:** a thing.\n\n"
                        f"**Blocked by:** {blocked}\n\n**Status:** {status}\n")
        return path

    def rows(self, *sessions, track="checkout"):
        sessions = sessions or (self.boss("b", self.loom, track),)
        column = next(c for c in self.claude(*sessions)["columns"] if c["raw"] == track)
        return column["track"]["rows"]

    def states(self, *sessions):
        return [(r["text"], r["state"]) for r in self.rows(*sessions)]

    def elsewhere(self, *sessions, track="checkout"):
        sessions = sessions or (self.boss("b", self.loom, track),)
        column = next(c for c in self.claude(*sessions)["columns"] if c["raw"] == track)
        return column["track"]["elsewhere"]


class Rows(Fixtures):
    def test_a_ticked_line_is_done_and_an_unticked_line_naming_no_ticket_is_planned(self):
        self.goal("[x] the cart keeps a card", "[ ] the full suite is green")
        self.assertEqual(self.states(), [("the full suite is green", "planned"),
                                         ("the cart keeps a card", "done")])

    def test_a_line_carries_the_tickets_it_names_with_title_status_and_blocked_by(self):
        self.goal("[ ] `paste/12` at Status done: the copy button shows")
        self.ticket("paste/12", status="needs-triage", title="The copy button", blocked="None")
        row, = self.rows()
        self.assertEqual(row["tickets"], [{"ref": "paste/12", "title": "12: The copy button",
                                           "status": "needs-triage", "blocked_by": "None", "workers": []}])

    def test_an_unticked_line_whose_tickets_are_all_done_is_worked_on_and_awaits_its_tick(self):
        self.goal("[ ] paste/12 at Status done", "[ ] paste/13 at Status done")
        self.ticket("paste/12", status="done")
        self.ticket("paste/13", status="needs-triage")
        got = {r["text"]: (r["state"], r["awaiting_tick"]) for r in self.rows()}
        self.assertEqual(got, {"paste/12 at Status done": ("worked", True),
                               "paste/13 at Status done": ("planned", False)})

    def test_a_ticked_line_is_done_whatever_its_tickets_say(self):
        self.goal("[x] paste/12 at Status done")
        self.ticket("paste/12", status="needs-triage")
        self.assertEqual(self.states(), [("paste/12 at Status done", "done")])

    def test_resolved_and_wontfix_count_as_done_for_a_ticket(self):
        self.goal("[ ] paste/12 and paste/13 closed")
        self.ticket("paste/12", status="resolved")
        self.ticket("paste/13", status="wontfix")
        row, = self.rows()
        self.assertEqual((row["state"], row["awaiting_tick"]), ("worked", True))

    def test_a_line_is_worked_on_when_a_live_worker_of_the_roster_has_its_ticket_in_its_task(self):
        self.goal("[ ] paste/12 done", "[ ] paste/13 done")
        self.ticket("paste/12"); self.ticket("paste/13")
        self.roster_of(("Mei", "paste/12 copy button while a question is open"), ("Odile", "paste/13 the reader"))
        got = self.rows(self.boss("b", self.loom, "checkout"),
                        self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual([(r["text"], r["state"]) for r in got],
                         [("paste/12 done", "worked"), ("paste/13 done", "planned")])
        self.assertEqual(got[0]["tickets"][0]["workers"], ["Mei"])

    def test_a_struck_through_roster_row_makes_nothing_worked(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        self.roster_of(("~~Mei~~", "paste/12 copy button"))
        got = self.rows(self.boss("b", self.loom, "checkout"),
                        self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual(got[0]["state"], "planned")

    def test_every_roster_table_of_the_tracker_counts_and_its_task_column_is_found_by_its_heading(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        (self.pm / "checkout.md").write_text(
            "# PM Tracker\n\n## Roster\n| Name | Pane | Project | Branch | Current task |\n|---|---|---|---|---|\n\n"
            "## Roster (2026-11-10 ~00:10)\n| Name | Pane | Project | Branch | Current task |\n|---|---|---|---|---|\n"
            "| Mei | %228 | agentview-wt/Mei | feat/paste-99 | paste/12 copy button |\n")
        got = self.rows(self.boss("b", self.loom, "checkout"),
                        self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual(got[0]["state"], "worked")

    def test_a_line_is_waiting_when_an_open_ticket_of_it_is_blocked_by_an_open_ticket(self):
        self.goal("[ ] marks/02 done", "[ ] marks/03 done", "[ ] marks/04 done")
        self.ticket("marks/01", status="needs-triage")
        self.ticket("marks/02", blocked="01: one marks store")
        self.ticket("marks/03", blocked="marks/05")             # no such ticket: nothing to wait on
        self.ticket("marks/04", blocked="02, 03")
        self.ticket("marks/06", status="done")
        got = {r["text"]: r["state"] for r in self.rows()}
        self.assertEqual(got, {"marks/02 done": "waiting", "marks/03 done": "planned", "marks/04 done": "waiting"})

    def test_a_ticket_blocked_only_by_done_tickets_is_not_waiting(self):
        self.goal("[ ] marks/02 done")
        self.ticket("marks/01", status="resolved")
        self.ticket("marks/02", blocked="01")
        self.assertEqual(self.states(), [("marks/02 done", "planned")])

    def test_rows_go_worked_waiting_planned_done_and_keep_the_goal_order_inside_a_state(self):
        self.goal("[x] one", "[ ] two", "[ ] marks/02 three", "[ ] four", "[x] five", "[ ] paste/12 six")
        self.ticket("marks/01"); self.ticket("marks/02", blocked="01"); self.ticket("paste/12", status="done")
        self.assertEqual(self.states(), [("paste/12 six", "worked"), ("marks/02 three", "waiting"),
                                         ("two", "planned"), ("four", "planned"),
                                         ("one", "done"), ("five", "done")])

    def test_a_range_names_every_ticket_in_it_and_is_done_only_when_all_are(self):
        self.goal("[ ] paste/23 to 26 at Status done", "[ ] paste/30-31 done")
        for n, status in ((23, "done"), (24, "done"), (25, "needs-triage"), (26, "done"), (30, "done"), (31, "wontfix")):
            self.ticket(f"paste/{n}", status=status)
        got = {r["text"]: ([t["ref"] for t in r["tickets"]], r["state"]) for r in self.rows()}
        self.assertEqual(got, {"paste/23 to 26 at Status done": (["paste/23", "paste/24", "paste/25", "paste/26"], "planned"),
                               "paste/30-31 done": (["paste/30", "paste/31"], "worked")})

    def test_one_worker_on_one_ticket_of_a_range_makes_the_line_worked(self):
        self.goal("[ ] paste/23 to 25 done")
        for n in (23, 24, 25):
            self.ticket(f"paste/{n}")
        self.roster_of(("Mei", "paste/24"))
        got = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual(got[0]["state"], "worked")

    def test_a_reference_to_no_ticket_file_and_a_path_are_no_tickets(self):
        self.goal("[ ] paste/99 done in agentview-wt/Mei on origin/dev, see src/12/x and 2026/11")
        self.ticket("paste/12")
        row, = self.rows()
        self.assertEqual((row["tickets"], row["state"]), ([], "planned"))

    def test_tickets_are_read_in_the_main_checkout_of_a_worker_in_a_worktree_and_in_another_repository(self):
        orchard = self.repo("orchard")
        tree = self.worktree(orchard, "orchard-wt-mei")
        self.goal("[ ] paste/12 done", "[ ] cards/03 done")
        self.ticket("paste/12", title="In loom")
        self.ticket("cards/03", title="In orchard", repo=orchard)
        self.ticket("cards/03", title="In the worktree", repo=tree)
        got = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", tree, "checkout", name="Mei"))
        self.assertEqual(sorted(t["title"] for r in got for t in r["tickets"]), ["03: In orchard", "12: In loom"])

    def test_a_ticket_that_links_out_of_its_scratch_folder_is_not_read(self):
        secret = self.disk / "secret.md"
        secret.write_text("# 12: a secret title\n**Status:** done\n")
        (self.loom / "notes.md").write_text("# 13: not a ticket\n**Status:** done\n")
        folder = self.loom / ".scratch" / "paste" / "issues"
        folder.mkdir(parents=True)
        (folder / "12-out.md").symlink_to(secret)
        (folder / "13-up.md").symlink_to(self.loom / "notes.md")
        self.goal("[ ] paste/12 done", "[ ] paste/13 done")
        self.assertEqual([r["tickets"] for r in self.rows()], [[], []])

    def test_a_card_reads_a_bounded_number_of_tickets(self):
        self.goal(*(f"[ ] paste/{n} done" for n in range(1, 61)))
        for n in range(1, 61):
            self.ticket(f"paste/{n}")
        got = sum(len(r["tickets"]) for r in self.rows())
        self.assertEqual(got, 40)

    def test_a_worker_of_the_roster_whose_session_is_gone_makes_nothing_worked(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        self.roster_of(("Mei", "paste/12 copy button"))
        got = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", self.loom, "checkout", name="Odile"))
        self.assertEqual((got[0]["state"], got[0]["tickets"][0]["workers"]), ("planned", []))

    def test_a_met_track_has_every_row_done_as_its_progress_says(self):
        self.goal("[x] one", "[ ] two")
        (self.pm / "checkout.goal.md").write_text(
            (self.pm / "checkout.goal.md").read_text().replace("_Status: OPEN_", "_Status: MET 2026-11-11_"))
        self.assertEqual(self.states(), [("one", "done"), ("two", "done")])

    def test_a_ticket_is_named_as_its_file_numbers_it(self):
        self.goal("[ ] turn-hook/1 done")
        self.ticket("turn-hook/01")
        row, = self.rows()
        self.assertEqual([t["ref"] for t in row["tickets"]], ["turn-hook/01"])

    def test_a_bold_struck_through_roster_row_is_retired_too(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        self.roster_of(("**~~Mei~~**", "paste/12 copy button"))
        got = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual(got[0]["state"], "planned")

    def test_blockers_never_take_the_budget_of_a_rows_own_tickets(self):
        self.goal(*(f"[ ] paste/{n} done" for n in range(1, 41)))
        for n in range(1, 41):
            self.ticket(f"paste/{n}", blocked=str(n + 40))
        self.assertEqual(sum(len(r["tickets"]) for r in self.rows()), 40)

    def test_a_track_with_no_boss_running_has_no_rows(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        self.config = {"assign": {"claude:s": "track:checkout"}}
        got = self.claude(sess("s", self.loom, name="Femi"))
        column = next(c for c in got["columns"] if c["project"] == "track:checkout")
        self.assertEqual(column["track"]["rows"], [])

    def test_a_row_whose_tickets_are_closed_awaits_its_tick_even_with_a_worker_still_on_the_roster(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12", status="done")
        self.roster_of(("Mei", "paste/12 copy button"))
        row, = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual((row["state"], row["awaiting_tick"]), ("worked", True))

    def test_a_boss_of_another_track_moved_into_a_track_gives_it_no_rows(self):
        self.goal("[ ] paste/12 done")
        self.ticket("paste/12")
        self.config = {"assign": {"claude:b2": "track:checkout"}}
        got = self.claude(self.boss("b2", self.loom, "docs", name="Saskia"), sess("s", self.loom, name="Femi"))
        column = next(c for c in got["columns"] if c["project"] == "track:checkout")
        self.assertEqual(column["track"]["rows"], [])

    def test_a_worker_listed_in_two_roster_tables_keeps_both_tasks(self):
        self.goal("[ ] paste/12 done", "[ ] paste/13 done")
        self.ticket("paste/12"); self.ticket("paste/13")
        (self.pm / "checkout.md").write_text(
            "# PM Tracker\n\n## Roster\n| Name | Current task |\n|---|---|\n| Mei | paste/12 copy button |\n\n"
            "## Roster (later)\n| Name | Current task |\n|---|---|\n| Mei | paste/13 the reader |\n")
        got = self.rows(self.boss("b", self.loom, "checkout"), self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertEqual([r["state"] for r in got], ["worked", "worked"])

    def test_a_live_worker_whose_task_ties_to_no_line_is_shown_with_its_task(self):
        self.goal("[ ] the cart keeps a card", "[ ] paste/12 done")
        self.ticket("paste/12")
        self.roster_of(("Mei", "#09c waiver and token"), ("Odile", "paste/12 the reader"))
        got = self.elsewhere(self.boss("b", self.loom, "checkout"),
                             self.worker("w", self.loom, "checkout", name="Mei"),
                             self.worker("v", self.loom, "checkout", name="Odile"))
        self.assertEqual(got, [{"name": "Mei", "task": "#09c waiver and token", "busy": True, "watching": False}])

    def test_a_worker_gone_or_struck_through_or_with_no_task_is_not_shown_elsewhere(self):
        self.goal("[ ] the cart keeps a card")
        self.roster_of(("Mei", "#09c waiver"), ("~~Odile~~", "#26 edge cases"), ("Ines", ""), ("Zoe", "idle"))
        got = self.elsewhere(self.boss("b", self.loom, "checkout"),
                             self.worker("w", self.loom, "checkout", name="Odile"),
                             self.worker("v", self.loom, "checkout", name="Ines"),
                             self.worker("u", self.loom, "checkout", name="Zoe"))
        self.assertEqual(got, [])

    def test_a_card_that_is_no_running_track_has_nobody_elsewhere(self):
        self.goal("[ ] the cart keeps a card")
        self.roster_of(("Mei", "#09c waiver"))
        got = self.claude(self.worker("w", self.loom, "checkout", name="Mei"))
        self.assertTrue(all(c["track"].get("elsewhere", []) == [] for c in got["columns"] if c.get("track")))

class Panes(Fixtures):
    """Sessions on tmux panes, with no concierge mark and no stamp until a test lays them."""

    def setUp(self):
        super().setUp()
        for name in ("_pane_roles", "_pane_owners"):
            self.addCleanup(setattr, fleet, name, getattr(fleet, name))
        fleet._pane_roles = lambda now=None: frozenset()
        fleet._pane_owners = lambda now=None: {}
        self.goal("[ ] the cart keeps a card", "[ ] paste/12 done")
        self.ticket("paste/12")

    def at(self, sid, name, pane, **over):
        over.setdefault("status", "busy")
        return sess(sid, self.loom, name=name, tmux=f"boss-checkout:@3.{pane}", **over)


class Working(Panes):
    """Who counts as working (ticket boss-track/06): a busy or waiting session
    that is no concierge. Idle is never work. Idle with a job open is no work either,
    but its worker is listed with the 🧪 sign (ticket boss-track/18, class `Watching`)."""

    def test_an_idle_worker_with_no_job_is_on_no_line_and_not_elsewhere(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "paste/12 the reader"), ("Ines", "#18 MERGED, done, idle"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle"),
                    self.at("v", "Odile", "%32", status="idle"), self.at("u", "Ines", "%33", status="idle"))
        self.assertEqual(self.elsewhere(*sessions), [])
        self.assertEqual([r["state"] for r in self.rows(*sessions)], ["planned", "planned"])

    def test_a_waiting_session_is_working_and_so_is_a_busy_one(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"),
                    self.at("w", "Mei", "%31", status="waiting"), self.at("v", "Odile", "%32"))
        self.assertEqual([r["state"] for r in self.rows(*sessions)], ["worked", "planned"])
        self.assertEqual(self.elsewhere(*sessions), [{"name": "Mei", "task": "#09c waiver", "busy": False, "watching": False}])

    def test_a_concierge_is_never_a_worker_by_its_pane_mark_or_by_its_task(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "concierge"), ("Ines", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31"),
                    self.at("v", "Odile", "%32"), self.at("u", "Ines", "%34"))
        fleet._pane_roles = lambda now=None: frozenset({"%31", "%34"})
        self.assertEqual(self.elsewhere(*sessions), [])
        self.assertEqual([r["state"] for r in self.rows(*sessions)], ["planned", "planned"])

    def test_a_card_shaped_on_the_live_one_lists_the_busy_worker_and_the_one_watching_a_job(self):
        # insights-bento at 19:2x: a concierge, a worker with a job open, two merged and idle, one busy.
        self.roster_of(("Ana", "concierge"), ("Bo", "#09c waiver, tests running"), ("Cy", "#18 MERGED 44273ab, fix round"),
                       ("Di", "#10 MERGED 38b79b3. Done, idle"), ("Ed", "#15 MERGED 980d907. Done, idle"))
        fleet._pane_roles = lambda now=None: frozenset({"%31"})
        got = self.elsewhere(self.boss("b", self.loom, "checkout"),
                             self.at("a", "Ana", "%31", status="idle"), self.at("bo", "Bo", "%32", status="idle", **JOB),
                             self.at("c", "Cy", "%33"), self.at("d", "Di", "%34", status="idle"),
                             self.at("e", "Ed", "%35", status="idle"))
        self.assertEqual(got, [{"name": "Bo", "task": "#09c waiver, tests running", "busy": False, "watching": True},
                               {"name": "Cy", "task": "#18 MERGED 44273ab, fix round", "busy": True, "watching": False}])


class Stamped(Panes):
    """A track's workers from the tmux stamps (ticket boss-track/07): the panes
    claude-boss stamped `@boss_pane` with the boss's pane, for a tracker with no
    table naming them. The fixtures are shaped on an empty table beside a prose roster."""

    def setUp(self):
        super().setUp()
        fleet._pane_owners = lambda now=None: {"%31": "%30", "%32": "%30", "%33": "%30", "%35": "%99"}

    def boss_at(self):
        return sess("b", self.loom, name="Ilse", boss=True, track="checkout", tmux="boss-checkout:@3.%30")

    def prose_roster(self):
        (self.pm / "checkout.md").write_text(
            "# PM Tracker - checkout\n\n## Roster\n| Name | Pane | Current task |\n|---|---|---|\n\n"
            "## Roster (2026-11-12 13:00, the boss)\nMei (%31) ticket 26. Odile (%32) PR 248.\n")

    def track(self, said, *sessions):
        """The card's track, each session having written `said[id]` as its line."""
        for sid, did in said.items():
            lines.write(sid, did=did, root=self.lines)
        column = next(c for c in self.claude(self.boss_at(), *sessions)["columns"] if c["raw"] == "checkout")
        return column["track"]

    def test_a_worker_on_a_prose_roster_is_shown_with_what_it_last_said_and_hammers_its_line(self):
        self.prose_roster()
        got = self.track({"w": "paste/12 the reader, tests red", "v": "waiting for review of PR 248"},
                         self.at("w", "Mei", "%31"), self.at("v", "Odile", "%32"))
        self.assertEqual([r["state"] for r in got["rows"]], ["worked", "planned"])
        self.assertEqual(got["elsewhere"], [{"name": "Odile", "task": "waiting for review of PR 248", "busy": True, "watching": False}])

    def test_a_stamped_worker_watching_a_job_with_no_ref_in_its_words_is_listed_elsewhere_watching(self):
        # Naya, 2026-11-13: no Roster table, words that name `private-root-4 / #467` and no `feature/NN`.
        self.prose_roster()
        got = self.track({"w": "waiting for the full run of #467, then PR"},
                         self.at("w", "Mei", "%31", status="idle", **JOB))
        self.assertEqual(got["elsewhere"], [{"name": "Mei", "task": "waiting for the full run of #467, then PR", "busy": False, "watching": True}])
        self.assertEqual([r["state"] for r in got["rows"]], ["planned", "planned"])

    def test_the_tables_task_wins_over_the_last_line_and_a_session_outside_the_table_needs_a_stamp(self):
        self.roster_of(("Mei", "paste/12 the reader"))
        got = self.track({"w": "something else entirely", "u": "ticket 26 in review"},
                         self.at("w", "Mei", "%31"), self.at("u", "Zoe", "%40"))
        self.assertEqual([r["state"] for r in got["rows"]], ["worked", "planned"])
        self.assertEqual(got["elsewhere"], [])

    def test_the_workers_own_line_is_what_elsewhere_says_when_the_cell_names_no_ticket(self):
        """Ticket boss-track/21: a cell nobody refreshed ("fresh, parked") does not speak for a worker who says what it does."""
        self.roster_of(("Mei", "fresh, parked"), ("Odile", "fresh, parked"))
        got = self.track({"w": "PR 48 head c5f7dc6, only the suite is left"},
                         self.at("w", "Mei", "%31"), self.at("v", "Odile", "%32"))
        self.assertEqual(got["elsewhere"], [{"name": "Mei", "task": "PR 48 head c5f7dc6, only the suite is left", "busy": True, "watching": False},
                                            {"name": "Odile", "task": "fresh, parked", "busy": True, "watching": False}])

    def test_the_cell_still_places_the_worker_on_its_ticket_whatever_the_line_says(self):
        """Ticket boss-track/21: matching keeps reading the cell."""
        self.roster_of(("Mei", "paste/12 the reader"))
        got = self.track({"w": "something else entirely"}, self.at("w", "Mei", "%31"))
        self.assertEqual(([r["state"] for r in got["rows"]], got["rows"][0]["tickets"][0]["workers"], got["elsewhere"]),
                         (["worked", "planned"], ["Mei"], []))

    def test_an_idle_cell_keeps_the_worker_off_the_card_even_with_a_line(self):
        """Ticket boss-track/21: the line replaces the words shown, never the idle verdict."""
        self.roster_of(("Mei", "idle"))
        self.assertEqual(self.track({"w": "building PR 48"}, self.at("w", "Mei", "%31"))["elsewhere"], [])

    def test_a_pane_stamped_to_another_boss_and_a_concierge_are_not_workers(self):
        self.prose_roster()
        fleet._pane_roles = lambda now=None: frozenset({"%33"})
        got = self.track({"o": "ticket 1", "c": "ticket 2"},
                         self.at("o", "Pia", "%35"), self.at("c", "Cora", "%33"))
        self.assertEqual(got["elsewhere"], [])

    def test_a_busy_stamped_worker_with_no_table_row_and_no_line_is_listed_by_the_best_text_the_server_has(self):
        """Ticket boss-track/11: the card title, else the first line of the last prompt, else the word working."""
        self.prose_roster()
        got = self.track({}, self.at("w", "Mei", "%31", title="Fixing the reader"),
                         self.at("v", "Odile", "%32", prompt="Review PR 248\nand report back"),
                         self.at("u", "Anik", "%33"))
        self.assertEqual(got["elsewhere"], [{"name": "Anik", "task": "working", "busy": True, "watching": False},
                                            {"name": "Mei", "task": "Fixing the reader", "busy": True, "watching": False},
                                            {"name": "Odile", "task": "Review PR 248", "busy": True, "watching": False}])

    def test_a_worker_with_no_line_title_or_prompt_shows_the_first_line_of_its_newest_dispatch(self):
        """Ticket boss-track/22: before the word working; every better word still wins."""
        self.prose_roster()
        fleet._pane_owners = lambda now=None: {"%31": "%30", "%32": "%30", "%33": "%30", "%34": "%30"}
        got = self.track({"v": "waiting for review of PR 248"},
                         self.at("w", "Mei", "%31", dispatch="Ticket 52: fix the reader"),
                         self.at("v", "Odile", "%32", dispatch="Ticket 9: ignored"),
                         self.at("u", "Anik", "%33"),
                         self.at("t", "Zoe", "%34", title="Reader", dispatch="Ticket 9: ignored"))
        self.assertEqual([(e["name"], e["task"]) for e in got["elsewhere"]],
                         [("Anik", "working"), ("Mei", "Ticket 52: fix the reader"),
                          ("Odile", "waiting for review of PR 248"), ("Zoe", "Reader")])

    def test_a_table_cell_that_says_idle_wins_over_the_stamp(self):
        """Ticket boss-track/11: only an empty cell falls through."""
        self.roster_of(("Mei", "idle"))
        self.assertEqual(self.track({"w": "paste/12 the reader"}, self.at("w", "Mei", "%31"))["elsewhere"], [])

    def test_a_table_row_with_an_empty_task_cell_falls_through_to_the_line_and_the_title(self):
        """Ticket boss-track/11: an empty cell names no task, so the worker's own words are used."""
        self.roster_of(("Mei", ""), ("Odile", ""))
        got = self.track({"w": "paste/12 the reader"},
                         self.at("w", "Mei", "%31"), self.at("v", "Odile", "%32", title="Reader"))
        self.assertEqual([r["state"] for r in got["rows"]], ["worked", "planned"])
        self.assertEqual(got["elsewhere"], [{"name": "Odile", "task": "Reader", "busy": True, "watching": False}])

    def test_the_last_line_wins_over_the_title_and_the_title_over_the_prompt(self):
        self.prose_roster()
        got = self.track({"w": "waiting for review of PR 248"},
                         self.at("w", "Mei", "%31", title="Fixing the reader", prompt="go"),
                         self.at("v", "Odile", "%32", title="Reader", prompt="go"))
        self.assertEqual(got["elsewhere"], [{"name": "Mei", "task": "waiting for review of PR 248", "busy": True, "watching": False},
                                            {"name": "Odile", "task": "Reader", "busy": True, "watching": False}])

    def test_an_idle_stamped_worker_is_shown_nowhere(self):
        self.prose_roster()
        got = self.track({"w": "paste/12 merged, parked"}, self.at("w", "Mei", "%31", status="idle"))
        self.assertEqual((got["elsewhere"], [r["state"] for r in got["rows"]]), ([], ["planned", "planned"]))


class Busy(Panes):
    """Which hammers swing (ticket boss-track/17): a worker whose turn is in flight.
    A question open (`waiting`) is a still hammer; a finished turn with a job open
    is a worker since ticket boss-track/18, shown with 🧪, never a swinging hammer."""

    def test_a_busy_worker_makes_its_row_and_its_elsewhere_entry_busy(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"),
                    self.at("w", "Mei", "%31"), self.at("v", "Odile", "%32"))
        self.assertEqual([r["busy"] for r in self.rows(*sessions)], [True, False])
        self.assertEqual(self.elsewhere(*sessions), [{"name": "Mei", "task": "#09c waiver", "busy": True, "watching": False}])

    def test_a_worker_with_a_question_open_is_worked_but_not_busy(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"),
                    self.at("w", "Mei", "%31", status="waiting"), self.at("v", "Odile", "%32", status="waiting"))
        rows = self.rows(*sessions)
        self.assertEqual([(r["state"], r["busy"]) for r in rows], [("worked", False), ("planned", False)])
        self.assertEqual(self.elsewhere(*sessions), [{"name": "Mei", "task": "#09c waiver", "busy": False, "watching": False}])

    def test_a_session_whose_turn_is_over_with_a_job_open_is_worked_and_not_busy(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"),
                    self.at("w", "Mei", "%31", **JOB), self.at("v", "Odile", "%32", **JOB))
        self.assertEqual([(r["state"], r["busy"]) for r in self.rows(*sessions)], [("worked", False), ("planned", False)])
        self.assertEqual(self.elsewhere(*sessions), [{"name": "Mei", "task": "#09c waiver", "busy": False, "watching": True}])

    def test_a_row_with_several_workers_is_busy_when_any_one_is(self):
        self.roster_of(("Mei", "paste/12 the reader"), ("Odile", "paste/12 the copy button"))
        for mei, odile in (("waiting", "busy"), ("busy", "waiting"), ("waiting", "waiting")):
            with self.subTest(mei=mei, odile=odile):
                sessions = (self.boss("b", self.loom, "checkout"),
                            self.at("w", "Mei", "%31", status=mei), self.at("v", "Odile", "%32", status=odile))
                row = self.rows(*sessions)[0]
                self.assertEqual((row["state"], row["busy"]), ("worked", "busy" in (mei, odile)))

    def test_a_busy_boss_of_the_same_name_does_not_make_a_waiting_worker_busy(self):
        self.roster_of(("Mei", "#09c waiver"))
        sessions = (self.boss("b", self.loom, "checkout", name="Mei", status="busy"),
                    self.at("w", "Mei", "%31", status="waiting"))
        self.assertEqual(self.elsewhere(*sessions), [{"name": "Mei", "task": "#09c waiver", "busy": False, "watching": False}])

    def test_a_row_nobody_works_on_is_not_busy(self):
        self.assertEqual([r["busy"] for r in self.rows()], [False, False])


class Watching(Panes):
    """A worker whose turn is over with a job of its own open keeps the 🧪 sign
    on its objective (ticket boss-track/18)."""

    def test_idle_with_a_job_open_marks_its_row_watching_and_not_busy(self):
        self.roster_of(("Mei", "paste/12 the reader"))
        row = self.rows(self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB))[0]
        self.assertEqual((row["state"], row["busy"], row["watching"], row["tickets"][0]["workers"]),
                         ("worked", False, True, ["Mei"]))

    def test_a_row_whose_workers_all_watch_jobs_is_worked_not_waiting(self):
        self.roster_of(("Mei", "paste/12 the reader"), ("Odile", "paste/12 the copy button"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB),
                    self.at("v", "Odile", "%32", **JOB))
        self.assertEqual([(r["state"], r["busy"], r["watching"]) for r in self.rows(*sessions)],
                         [("worked", False, True), ("planned", False, False)])

    def test_one_busy_worker_beside_a_watching_one_swings_the_row(self):
        self.roster_of(("Mei", "paste/12 the reader"), ("Odile", "paste/12 the copy button"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB),
                    self.at("v", "Odile", "%32"))
        self.assertTrue(self.rows(*sessions)[0]["busy"])

    def test_a_row_of_a_blocked_ticket_is_worked_when_its_only_worker_watches_a_job(self):
        self.ticket("paste/13", blocked="paste/12")
        self.goal("[ ] paste/13 done")
        self.roster_of(("Mei", "paste/13 the copy button"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB))
        self.assertEqual([(r["state"], r["busy"]) for r in self.rows(*sessions)], [("worked", False)])
        self.assertEqual(self.states(self.boss("b", self.loom, "checkout"))[0][1], "waiting")

    def test_a_watching_worker_whose_roster_cell_says_idle_stays_out(self):
        self.roster_of(("Mei", "idle"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB))
        self.assertEqual(self.elsewhere(*sessions), [])
        self.assertEqual(self.rows(*sessions)[0]["state"], "planned")

    def test_the_row_is_watching_only_when_every_worker_of_the_row_watches(self):
        self.roster_of(("Mei", "paste/12 the reader"), ("Odile", "paste/12 the copy button"))
        for mei, odile, busy, watching in (
                (dict(status="idle", **JOB), dict(status="idle", **JOB), False, True),
                (dict(status="idle", **JOB), dict(status="busy"), True, False),         # swinging beats the watching sign
                (dict(status="idle", **JOB), dict(status="waiting"), False, False)):    # a still hammer beats it
            with self.subTest(odile=odile["status"]):
                sessions = (self.boss("b", self.loom, "checkout"),
                            self.at("w", "Mei", "%31", **mei), self.at("v", "Odile", "%32", **odile))
                row = self.rows(*sessions)[0]
                self.assertEqual((row["busy"], row["watching"]), (busy, watching))

    def test_each_elsewhere_entry_carries_its_own_sign(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "#10 reader"), ("Ines", "#11 copy"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle", **JOB),
                    self.at("v", "Odile", "%32"), self.at("u", "Ines", "%33", status="waiting"))
        self.assertEqual([(e["name"], e["busy"], e["watching"]) for e in self.elsewhere(*sessions)],
                         [("Ines", False, False), ("Mei", False, True), ("Odile", True, False)])

    def test_idle_with_no_job_stays_out(self):
        self.roster_of(("Mei", "paste/12 the reader"))
        sessions = (self.boss("b", self.loom, "checkout"), self.at("w", "Mei", "%31", status="idle"))
        self.assertEqual(self.elsewhere(*sessions), [])
        self.assertEqual(self.rows(*sessions)[0]["state"], "planned")

    def test_a_concierge_and_a_boss_with_a_job_open_stay_out(self):
        self.roster_of(("Mei", "#09c waiver"), ("Odile", "concierge"))
        fleet._pane_roles = lambda now=None: frozenset({"%31"})
        sessions = (self.boss("b", self.loom, "checkout", status="idle", **JOB),
                    self.at("w", "Mei", "%31", status="idle", **JOB), self.at("v", "Odile", "%32", status="idle", **JOB))
        self.assertEqual(self.elsewhere(*sessions), [])


if __name__ == "__main__":
    unittest.main()
