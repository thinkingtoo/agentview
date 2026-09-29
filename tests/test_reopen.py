"""A search result reopens its conversation, or jumps to it if it runs.

Reopening goes the closed list's way: `claude --resume` with the old flags, in
the old directory, under the old name. What differs is where the record comes
from. The newest snapshot that had the conversation says, as for the closed
list; snapshots only go back a few days, so for anything older the transcript
does: the directory it ran in and the permission mode it last ran under.
Nothing here comes from a real transcript.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import snapshot  # noqa: E402

SID = "00000000-0000-4000-8000-0000000000c1"


def snap(taken_at, boot, *sessions):
    return {"version": 2, "taken_at": taken_at, "boot_id": boot, "sessions": list(sessions),
            "tmux": [], "wezterm": [], "terminals": []}


def session(name, cwd="/home/alice/Projects/maple", flags="", sid=SID):
    return {"sessionId": sid, "name": name, "cwd": cwd, "flags": flags}


def transcript(folder, *records):
    path = Path(tempfile.mkdtemp()) / folder / f"{SID}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    return path


def said(cwd, mode=None):
    rec = {"type": "user", "sessionId": SID, "cwd": cwd, "message": {"role": "user", "content": "hi"}}
    return {**rec, "permissionMode": mode} if mode else rec


class FromSnapshot(unittest.TestCase):
    def test_the_newest_snapshot_that_had_it_gives_the_record_whatever_the_boot(self):
        snaps = [snap(100, "boot-a", session("Nimbus", flags="--model opus")),
                 snap(300, "boot-b", session("Other", sid="someone-else")),
                 snap(200, "boot-b", session("Nimbus", flags="--permission-mode auto"))]
        rec = snapshot.revive_record(SID, snaps, name="Indexed")
        self.assertEqual(rec, {"sessionId": SID, "name": "Nimbus", "cwd": "/home/alice/Projects/maple",
                               "flags": "--permission-mode auto", "from": "snapshot"})

    def test_a_snapshot_without_a_name_takes_the_one_the_index_knows(self):
        rec = snapshot.revive_record(SID, [snap(100, "boot-a", session(""))], name="Nimbus")
        self.assertEqual(rec["name"], "Nimbus")


class FromTranscript(unittest.TestCase):
    def test_older_than_every_snapshot_it_comes_from_the_transcript(self):
        path = transcript("-home-alice-Projects-maple",
                          said("/home/alice/Projects/maple", "plan"),
                          {"type": "permission-mode", "permissionMode": "default", "sessionId": SID},
                          said("/home/alice/Projects/maple/src", "acceptEdits"))
        rec = snapshot.revive_record(SID, [snap(100, "boot-a", session("X", sid="another"))],
                                     transcript=path, name="Nimbus")
        self.assertEqual(rec, {"sessionId": SID, "name": "Nimbus", "cwd": "/home/alice/Projects/maple",
                               "flags": "--permission-mode acceptEdits", "from": "transcript"})

    def test_the_directory_is_the_one_the_transcript_is_filed_under(self):
        # A conversation that moved into a subdirectory is still filed under
        # the one it started in, and `--resume` looks for it there.
        path = transcript("-home-alice-Projects-maple",
                          said("/home/alice/Projects/maple/src"),
                          said("/home/alice/Projects/maple"))
        self.assertEqual(snapshot.revive_record(SID, [], transcript=path)["cwd"],
                         "/home/alice/Projects/maple")

    def test_default_is_asked_for_by_name(self):
        # Left out, the flag would give whatever settings.json makes the
        # default, which is not what the conversation ran under.
        path = transcript("-home-alice-Projects-maple",
                          said("/home/alice/Projects/maple", "auto"),
                          {"type": "permission-mode", "permissionMode": "default", "sessionId": SID})
        self.assertEqual(snapshot.revive_record(SID, [], transcript=path)["flags"],
                         "--permission-mode default")

    def test_every_mode_the_cli_accepts_is_asked_for_by_the_name_it_knows(self):
        # `manual` is the cli's other spelling of `default`, and the only one
        # it takes that the transcript's own vocabulary does not use.
        for written, asked in (("acceptEdits", "acceptEdits"), ("auto", "auto"),
                               ("bypassPermissions", "bypassPermissions"), ("default", "default"),
                               ("manual", "default"), ("dontAsk", "dontAsk"), ("plan", "plan")):
            path = transcript("-home-alice-Projects-maple", said("/home/alice/Projects/maple", written))
            self.assertEqual(snapshot.revive_record(SID, [], transcript=path)["flags"],
                             f"--permission-mode {asked}", written)

    def test_no_mode_or_one_claude_does_not_know_adds_no_flag(self):
        for mode in (None, "sideways"):
            path = transcript("-home-alice-Projects-maple", said("/home/alice/Projects/maple", mode))
            self.assertEqual(snapshot.revive_record(SID, [], transcript=path)["flags"], "")

    def test_with_neither_there_is_nothing_to_reopen(self):
        self.assertIsNone(snapshot.revive_record(SID, [], transcript=None))
        self.assertIsNone(snapshot.revive_record(SID, [], transcript=Path("/nonexistent/x.jsonl")))


class Starting(unittest.TestCase):
    """A claude launched for a conversation and not yet in the registry: no
    peer file, so the page cannot see it running, but it is not closed."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.proc, self.cfg = self.root / "proc", self.root / "cfg"
        (self.cfg / "sessions").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)

    def process(self, pid, *args):
        (self.proc / str(pid)).mkdir(parents=True)
        (self.proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")

    def test_a_claude_resuming_it_that_has_no_peer_file_yet_is_starting(self):
        self.process(101, "claude", "--resume", SID, "--permission-mode", "auto")
        self.assertEqual(snapshot.starting(SID, proc=self.proc, cfg=self.cfg), [101])

    def test_one_with_a_peer_file_is_the_registrys_to_answer_for(self):
        # Started with --resume A, then /resume B inside it: A is not running
        # in it any more, whatever its command line still says.
        self.process(101, "claude", "--resume", SID)
        (self.cfg / "sessions" / "101.json").write_text(json.dumps({"pid": 101, "sessionId": "another"}))
        self.assertEqual(snapshot.starting(SID, proc=self.proc, cfg=self.cfg), [])

    def test_other_conversations_and_other_programs_do_not_count(self):
        self.process(101, "claude", "--resume", "another-conversation")
        self.process(102, "grep", "--resume", SID)
        self.process(103, "claude", "-c", SID)
        self.process(104, "bash", "-c", f"claude --resume {SID}")     # a command line, not a claude
        self.assertEqual(snapshot.starting(SID, proc=self.proc, cfg=self.cfg), [])


class Endpoint(unittest.TestCase):
    """The route a click on a search result calls, over HTTP, against a
    throwaway ~/.claude. WezTerm is never touched: opening a tab and raising
    a window are replaced by recorders."""

    def setUp(self):
        import archive, log, server
        self.archive, self.log, self.server = archive, log, server
        self.root = Path(tempfile.mkdtemp())
        self.work = self.root / "work"                    # where the conversation ran
        self.work.mkdir()
        self.env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.root)
        self.old_log, log.LOG = log.LOG, self.root / "events.jsonl"
        server._SNAP.update(files=None, snap=None, latest=None, all=[])
        server._OPENING.clear()
        self.opened, self.jumped, self.delay = [], [], 0
        for target, new in (
                ("jump.open_tab", self.open_tab),
                ("snapshot.starting", lambda sid: []),
                ("snapshot.seed_name", lambda sid, name: self.seeded.append((sid, name))),
                ("snapshot.wez_guis", lambda: []),
                ("fleet.jump_to", lambda p, s: self.jumped.append(s["id"]) or {"ok": True, "ran": ["raise"]})):
            patch = mock.patch(target, new)
            patch.start()
            self.addCleanup(patch.stop)
        self.seeded = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def open_tab(self, argv, cwd=None):
        time.sleep(self.delay)               # wezterm takes a moment; so does the race
        self.opened.append((argv, cwd))
        return {"ok": True, "ran": ["spawn"], "pane": "7"}

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.log.LOG = self.old_log
        if self.env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.env
        shutil.rmtree(self.root)

    def conversation(self, cwd=None, name="Nimbus", mode="plan"):
        """A transcript the index has read, in the shape Claude Code writes."""
        cwd = str(cwd or self.work)
        folder = self.root / "projects" / snapshot.registry._encode(cwd)
        folder.mkdir(parents=True)
        recs = [{"type": "user", "sessionId": SID, "entrypoint": "cli", "cwd": cwd,
                 "isSidechain": False, "uuid": "u1", "timestamp": "2026-09-01T09:00:00.000Z",
                 "origin": {"kind": "human"}, "permissionMode": mode,
                 "message": {"role": "user", "content": "where did the kettle go?"}},
                {"type": "agent-name", "agentName": name, "sessionId": SID}]
        (folder / f"{SID}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n"
                                                     for r in recs))
        self.archive.update(path=self.root / "agentview" / "archive.db", root=self.root / "projects",
                            cfg=self.root, logs=[self.root / "none.jsonl"])

    def running(self):
        """A peer file for a process that is alive: this one."""
        stat = Path("/proc/self/stat").read_text()
        (self.root / "sessions").mkdir(exist_ok=True)
        (self.root / "sessions" / f"{os.getpid()}.json").write_text(json.dumps({
            "pid": os.getpid(), "sessionId": SID, "name": "Nimbus", "cwd": str(self.work),
            "kind": "interactive", "entrypoint": "sdk-cli", "status": "idle",
            "procStart": stat[stat.rindex(")") + 2:].split()[19]}))

    def snapshotted(self, *sessions):
        store = self.root / "agentview" / "snapshots"
        store.mkdir(parents=True)
        (store / "20260928T090000.json").write_text(json.dumps(snap(1790000000, "boot-a", *sessions)))

    def reopen(self, sid=SID):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_port}/api/reopen", method="POST",
            data=json.dumps({"id": sid}).encode(), headers={"X-Fleet": "1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def events(self, kind):
        return [json.loads(l) for l in self.log.LOG.read_text().splitlines() if f'"{kind}"' in l]

    def test_a_running_conversation_jumps_and_is_never_resumed_again(self):
        self.conversation()
        self.running()
        got = self.reopen()
        self.assertEqual((got["ok"], got["did"]), (True, "jumped"))
        self.assertEqual((self.jumped, self.opened, self.seeded), ([SID], [], []))
        self.assertEqual(self.events("jumped")[0]["key"], f"claude:{SID}")

    def test_a_closed_one_older_than_every_snapshot_opens_from_its_transcript_under_its_name(self):
        self.conversation()
        got = self.reopen()
        self.assertEqual((got["ok"], got["did"]), (True, "opened"))
        self.assertEqual(self.opened, [(["claude", "--resume", SID, "--permission-mode", "plan"],
                                        str(self.work))])
        self.assertEqual(self.seeded, [(SID, "Nimbus")])
        self.assertEqual(self.jumped, [])

    def test_a_closed_one_a_snapshot_remembers_opens_with_the_snapshots_flags(self):
        self.conversation(mode="default")
        self.snapshotted(session("Renamed", cwd=str(self.work), flags="--model opus"))
        self.reopen()
        self.assertEqual(self.opened, [(["claude", "--resume", SID, "--model", "opus"], str(self.work))])
        self.assertEqual(self.seeded, [(SID, "Renamed")])

    def test_when_the_directory_is_gone_nothing_is_launched(self):
        gone = self.root / "removed-worktree"
        self.conversation(cwd=gone)
        got = self.reopen()
        self.assertFalse(got["ok"])
        self.assertIn("directory is gone", got["reason"])
        self.assertIn(str(gone), got["reason"])
        self.assertEqual((self.opened, self.seeded), ([], []))

    def test_a_conversation_nobody_knows_is_refused(self):
        got = self.reopen("00000000-0000-4000-8000-0000000000ff")
        self.assertFalse(got["ok"])
        self.assertEqual(self.opened, [])

    def test_a_second_click_while_the_first_is_starting_opens_nothing_more(self):
        self.conversation()
        self.reopen()
        again = self.reopen()
        self.assertEqual((again["ok"], again["did"]), (True, "opening"))
        self.assertEqual(len(self.opened), 1)

    def test_two_clicks_at_the_same_moment_open_one_tab(self):
        self.conversation()
        self.delay = 0.4
        got = []
        clicks = [threading.Thread(target=lambda: got.append(self.reopen())) for _ in range(2)]
        for c in clicks:
            c.start()
        for c in clicks:
            c.join()
        self.assertEqual(sorted(g["did"] for g in got), ["opened", "opening"])
        self.assertEqual(len(self.opened), 1)

    def test_a_claude_launched_for_it_that_is_still_starting_is_not_resumed_again(self):
        self.conversation()
        with mock.patch("snapshot.starting", lambda sid: [4242] if sid == SID else []):
            got = self.reopen()
        self.assertEqual((got["ok"], got["did"]), (True, "opening"))
        self.assertEqual((self.opened, self.seeded), ([], []))

    def test_a_launch_that_failed_can_be_tried_again(self):
        self.conversation()
        with mock.patch("jump.open_tab", return_value={"ok": False, "reason": "wezterm cli spawn failed"}):
            self.assertFalse(self.reopen()["ok"])
        self.assertEqual(self.reopen()["did"], "opened")

    def test_each_reopen_is_logged_like_the_closed_lists_revives(self):
        self.conversation()
        self.reopen()
        (event,) = self.events("revived")
        self.assertEqual((event["id"], event["name"], event["source"], event["ok"]),
                         (SID, "Nimbus", "transcript", True))

    def test_a_refusal_is_logged_too(self):
        self.conversation(cwd=self.root / "removed-worktree")
        self.reopen()
        (event,) = self.events("revived")
        self.assertFalse(event["ok"])


if __name__ == "__main__":
    unittest.main()
