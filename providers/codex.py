"""Codex as a provider: the disk says what happened, `/proc` says who is alive.

Codex keeps three things worth reading, all under `~/.codex`:

- `state_5.sqlite`, table `threads`: cwd, git branch, title (the first prompt,
  truncated), model, tokens. No name -- `agent_nickname` is NULL on every
  one of 552 rows here.
- `sessions/YYYY/MM/DD/rollout-*.jsonl`: an append-only transcript, written
  from the moment the session starts. `event_msg` records carry the state:
  `task_started` is busy, `task_complete` and `turn_aborted` are idle,
  `agent_message` is what it said, `user_message` is what you asked.
- `thread-writer-locks/<thread-id>.lock`: appears when a session starts and
  goes when it ends cleanly. **It stays behind after a SIGKILL** -- verified
  2026-09-22 -- so the directory alone lies.

A session is live when its lock exists *and* a process holds the rollout
open. A live `codex` keeps that file in `/proc/<pid>/fd`, and the file name
carries the thread id, so pid and session match exactly. Where `/proc`
cannot be read (hidepid, a container, another user's process) the provider
degrades: the session shows without a jump. It never invents a pid.

Codex knows busy from idle and nothing about waiting, so it declares
neither `waiting` nor `status`; the chime never rings for it.
"""
import datetime
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

from providers.base import Provider, Tailed

# `source` in the thread table, said the page's way. `exec` is `codex exec`,
# a one-shot like `claude -p`; a review subagent is the JSON-ish third one.
KINDS = {"cli": "interactive", "exec": "exec"}
TITLE_LEN = 80


def _ms(stamp):
    """An ISO timestamp with a Z, as milliseconds epoch. 0 when unreadable."""
    if not isinstance(stamp, str):
        return 0
    try:
        when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return int(when.timestamp() * 1000)


def _blank():
    return {"offset": 0, "ino": None, "head": b"", "status": "", "statusAt": 0,
            "said": "", "prompt": "", "cwd": "", "startedAt": 0, "source": ""}


def _absorb(state, text):
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        kind, payload = rec.get("type"), rec.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if kind == "session_meta":
            state["cwd"] = payload.get("cwd") or state["cwd"]
            state["source"] = payload.get("source") or state["source"]
            state["startedAt"] = _ms(rec.get("timestamp")) or state["startedAt"]
            continue
        if kind != "event_msg":
            continue
        what = payload.get("type")
        if what == "task_started":
            state["status"], state["statusAt"] = "busy", _ms(rec.get("timestamp"))
        elif what in ("task_complete", "turn_aborted"):
            state["status"], state["statusAt"] = "idle", _ms(rec.get("timestamp"))
        elif what == "agent_message" and isinstance(payload.get("message"), str):
            state["said"] = payload["message"]
        elif what == "user_message" and isinstance(payload.get("message"), str):
            # Your next prompt ends the turn that said something.
            state["prompt"], state["said"] = payload["message"], ""
    return state


def _thread_id(name):
    """`rollout-2026-09-22T12-48-56-<uuid>.jsonl` -> the uuid, or ''."""
    stem = name[:-6] if name.endswith(".jsonl") else ""
    return stem[-36:] if len(stem) > 36 and stem.startswith("rollout-") else ""


class CodexProvider(Provider):
    name = "codex"
    capabilities = frozenset({"jump", "branch"})

    def __init__(self, home=None, proc="/proc"):
        self.home = Path(home) if home else Path.home() / ".codex"
        self.proc = Path(proc)
        self.tail = Tailed(_blank, _absorb)
        self.holders = {}      # thread id -> (pid, fd) seen holding its rollout
        self.orphans = {}      # thread id -> lock identity already found unheld

    # ------------------------------------------------------------ liveness

    def _locks(self):
        """thread id -> (inode, mtime) for every lock on disk."""
        out = {}
        try:
            entries = list((self.home / "thread-writer-locks").iterdir())
        except OSError:
            return out
        for path in entries:
            if path.name.startswith(".") or path.suffix != ".lock":
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            out[path.stem] = (st.st_ino, st.st_mtime_ns)
        return out

    def _codex_pids(self):
        out = []
        try:
            names = os.listdir(self.proc)
        except OSError:
            return out
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open(self.proc / name / "comm", encoding="utf-8") as fh:
                    if fh.read().strip() == "codex":
                        out.append(int(name))
            except OSError:
                continue
        return out

    def _held(self, pid, fd, tid):
        """Is this fd of this process still that thread's rollout?"""
        try:
            return _thread_id(os.path.basename(
                os.readlink(self.proc / str(pid) / "fd" / str(fd)))) == tid
        except OSError:
            return False

    def _resolve(self, locks):
        """thread id -> (pid, fd, rollout path) for the locks somebody holds.

        Remembered holders are re-checked with one readlink each. Only a
        lock with no holder on record walks `/proc` -- once, since an
        orphan is remembered by its lock's identity and not walked for
        again. Returns the map and whether some process could not be read.
        """
        found, denied = {}, False
        for tid, (pid, fd, path) in list(self.holders.items()):
            if tid in locks and self._held(pid, fd, tid):
                found[tid] = (pid, fd, path)
        missing = {tid for tid, ident in locks.items()
                   if tid not in found and self.orphans.get(tid) != ident}
        if missing:
            for pid in self._codex_pids():
                try:
                    fds = os.listdir(self.proc / str(pid) / "fd")
                except PermissionError:
                    denied = True
                    continue
                except OSError:
                    continue
                for fd in fds:
                    try:
                        target = os.readlink(self.proc / str(pid) / "fd" / fd)
                    except OSError:
                        continue
                    tid = _thread_id(os.path.basename(target))
                    if tid in missing:
                        found[tid] = (pid, int(fd), target)
            for tid in missing - set(found):
                if not denied:
                    self.orphans[tid] = locks[tid]
        self.holders = found
        return found, denied

    # ---------------------------------------------------------------- facts

    def _rows(self, tids):
        """What the thread table knows about these threads. Missing rows are
        fine: the rollout is written before the row, and says enough."""
        db = self.home / "state_5.sqlite"
        if not tids or not db.is_file():
            return {}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=0.5)
        try:
            marks = ",".join("?" * len(tids))
            cur = con.execute(
                "select id, rollout_path, cwd, title, git_branch, model, tokens_used,"
                " created_at_ms, source from threads where id in (%s)" % marks,
                list(tids))
            return {row[0]: dict(zip(("id", "rollout_path", "cwd", "title", "branch",
                                      "model", "tokens", "createdAt", "source"), row))
                    for row in cur}
        finally:
            con.close()

    def _rollout_for(self, tid, row):
        if row and row.get("rollout_path"):
            path = Path(row["rollout_path"])
            if path.is_file():
                return path
        # The table has no row yet: the file is under today's date, or near it.
        for hit in (self.home / "sessions").glob(f"*/*/*/rollout-*-{tid}.jsonl"):
            return hit
        return None

    def _session(self, tid, held, row):
        path = Path(held[2]) if held else self._rollout_for(tid, row)
        state = self.tail.scan(path) if path else _blank()
        quiet = None
        if path:
            try:
                quiet = (time.time() - path.stat().st_mtime) / 60
            except OSError:
                quiet = None
        row = row or {}
        source = state["source"] or row.get("source") or ""
        started = state["startedAt"] or (row.get("createdAt") or 0)
        title = " ".join((row.get("title") or "").split())
        if len(title) > TITLE_LEN:
            title = title[:TITLE_LEN - 1].rstrip() + "…"
        extras = {}
        if row.get("model"):
            extras["model"] = str(row["model"])
        if isinstance(row.get("tokens"), int) and row["tokens"] > 0:
            extras["tokens"] = f"{row['tokens'] / 1000:.0f}k"
        out = {
            "id": tid,
            "cwd": state["cwd"] or row.get("cwd") or "",
            # No status event yet -- a fresh session before its first turn --
            # is idle since it started.
            "status": state["status"] or "idle",
            "updatedAt": state["statusAt"] or started,
            "startedAt": started,
            "kind": KINDS.get(source, "review" if "review" in source else source or "?"),
            "branch": row.get("branch") or "",
            "title": title,
            "prompt": state["prompt"],
            "said": state["said"],
            "quietFor": quiet,
            "extras": extras,
        }
        if held:
            out["pid"] = held[0]
        return out

    def live(self):
        locks = self._locks()
        if not locks:
            return []
        held, denied = self._resolve(locks)
        # An orphan is nobody's session. Without a readable `/proc` it may
        # be somebody's after all, so it is shown -- without a pid.
        wanted = [tid for tid in locks if tid in held or denied]
        rows = self._rows(wanted)
        return [self._session(tid, held.get(tid), rows.get(tid))
                for tid in wanted]

    def find(self, session_id):
        for s in self.live():
            if s["id"] == session_id:
                if s.get("pid"):
                    s["tmux"] = self._tmux_target(s["pid"])
                return s
        return None

    def _tmux_target(self, pid):
        """`session:@window.%pane` for a process inside tmux, else ''.

        Only on a click: it costs a subprocess, and the poll must not.
        """
        try:
            with open(self.proc / str(pid) / "environ", "rb") as fh:
                env = dict(item.partition(b"=")[::2] for item in fh.read().split(b"\0") if item)
        except OSError:
            return ""
        pane = env.get(b"TMUX_PANE", b"").decode("ascii", "ignore")
        if not pane:
            return ""
        try:
            res = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane,
                 "#{session_name}:#{window_id}.#{pane_id}"],
                capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return ""
        return res.stdout.strip() if res.returncode == 0 else ""
