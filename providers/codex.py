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
neither `waiting` nor `status`; the chime never rings for it. What the rollout
does say, the overview reads: writes per minute, the error a turn ended in
(Limit or Error), an escalated command with no output yet (Needs you, inferred;
the session is then `waiting`), and for a `codex exec` run the processes above
it, which is how the roster finds the session that started it. It cannot say
Hung: a rollout is silent while a command runs, and nothing looks under the
process, so a busy session's silence is never called a hang.
"""
import datetime
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from providers import base, minutes, procs
from providers.base import Provider, Tailed

# `source` in the thread table, said the page's way. `exec` is `codex exec`,
# a one-shot like `claude -p`; a review subagent is the JSON-ish third one.
KINDS = {"cli": "interactive", "exec": "exec"}
# The kinds that are one-shot runs, started by something else.
RUNS = ("exec", "review")
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


# When a usage limit lifts, in the words Codex ends its message with: the time
# alone ("try again at 2:35 PM."), or with its day ("... at Oct 21st, 2026 3:14 AM.").
# Local time, with no zone: the machine that ran Codex wrote it.
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
RESETS = re.compile(r"try again at (?:([A-Za-z]{3}) (\d{1,2})(?:st|nd|rd|th), (\d{4}) )?"
                    r"(\d{1,2}):(\d{2}) ([AP]M)", re.I)


def _resets_at(message, at):
    """When the limit in this message lifts, milliseconds since 1970, or None.

    A time without a day is the next such time after the error (`at`, the
    moment it happened); a time with its day is that day's. None for words
    that are not one: a time that cannot be (25:99, a 31st of February) is no time.
    """
    hit = RESETS.search(message) if isinstance(message, str) else None
    if not hit or not at:
        return None
    month, day, year, hour, minute, half = hit.groups()
    hour, minute = int(hour), int(minute)
    if not 1 <= hour <= 12:
        return None
    hour = hour % 12 + (12 if half.upper() == "PM" else 0)
    try:
        if month:
            when = datetime.datetime(int(year), MONTHS.index(month.lower()) + 1, int(day), hour, minute)
        else:
            then = datetime.datetime.fromtimestamp(at / 1000)
            when = then.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when <= then:
                when += datetime.timedelta(days=1)
        return int(when.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return None


def _failure(error, stamp):
    """The error a turn ended in, as a provider hands it over (`base.py`), or
    None when it ended well. `codex_error_info` is a word, or an object holding
    the word and what goes with it (`{"http_connection_failed": {"http_status_code": 502}}`)."""
    if not isinstance(error, dict):
        return None
    info, status = error.get("codex_error_info"), None
    if isinstance(info, dict) and len(info) == 1:
        info, extra = next(iter(info.items()))
        status = base.whole_number(extra.get("http_status_code")) if isinstance(extra, dict) else None
    name = info if isinstance(info, str) else ""
    words = " ".join(error["message"].split()) if isinstance(error.get("message"), str) else ""
    at = _ms(stamp)
    return {"kind": "limit" if name == "usage_limit_exceeded" else "error",
            "type": name, "status": status,
            "text": words if len(words) <= base.FAILURE_LEN else words[:base.FAILURE_LEN - 1].rstrip() + "…",
            "at": at or None,
            "resetsAt": _resets_at(words, at) if name == "usage_limit_exceeded" else None}


# Calls kept while they wait for an output: more than this is a runaway, not a queue.
MAX_CALLS = 64
# The longest `arguments` text worth reading for a command.
MAX_ARGUMENTS = 200_000


def _command(args):
    """The command a call runs, as one text of at most `COMMAND_LIMIT` characters plus
    one when it had to be cut -- `cmd` is a text, an older `command` a list of words."""
    cmd = args.get("cmd", args.get("command"))
    if isinstance(cmd, list) and all(isinstance(word, str) for word in cmd):
        cmd = " ".join(cmd)
    return cmd[:base.COMMAND_LIMIT + 1] if isinstance(cmd, str) else ""


# A call is written two ways. Until August 2026 it is a `function_call` whose
# `arguments` are JSON. Since then it is a `custom_tool_call` whose `input` is a
# script that calls the tool, `await tools.exec_command({cmd: "...", ...})`. A
# script is read the way JavaScript reads it, as far as that goes: a text is one
# thing whatever it says, a comment is nothing, and only the object handed to
# the tool speaks for the call.
_NAME = re.compile(r"[A-Za-z_$][\w$]*|\d[\w.]*")
_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
_PLAIN = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_CALL = (("name", "tools"), (".", "."), ("name", "exec_command"), ("(", "("), ("{", "{"))


def _unescape(text):
    return _ESCAPE.sub(lambda m: chr(int(m.group(1)[1:], 16)) if len(m.group(1)) > 1
                       else _PLAIN.get(m.group(1), m.group(1)), text)


def _tokens(code):
    """A script as (kind, text) pairs: "text" for a quoted text (unescaped), "name"
    for a word or a number, the character itself for anything else. Comments and
    blanks are dropped. A text that is never closed ends the list: nothing after
    it can be told."""
    out, at = [], 0
    while at < len(code):
        ch = code[at]
        if ch.isspace():
            at += 1
        elif code.startswith("//", at):
            at = code.find("\n", at)
            if at < 0:
                break
        elif code.startswith("/*", at):
            at = code.find("*/", at + 2)
            if at < 0:
                break
            at += 2
        elif ch in "\"'`":
            close = at + 1
            while close < len(code) and code[close] != ch:
                close += 2 if code[close] == "\\" else 1
            if close >= len(code):
                break
            out.append(("text", _unescape(code[at + 1:close])))
            at = close + 1
        else:
            word = _NAME.match(code, at)
            out.append(("name", word.group()) if word else (ch, ch))
            at = word.end() if word else at + 1
    return out


def _script_arguments(code):
    """The objects a script hands to `tools.exec_command`, each as the keys at its
    top level whose value is a text: `{key: text}`. An object never closed is not one."""
    tokens, found = _tokens(code), []
    for start in range(len(tokens) - len(_CALL) + 1):
        if tuple(tokens[start:start + len(_CALL)]) != _CALL:
            continue
        keys, depth = {}, 0
        for i in range(start + len(_CALL) - 1, len(tokens)):
            kind, text = tokens[i]
            if kind in ("{", "[", "("):
                depth += 1
            elif kind in ("}", "]", ")"):
                depth -= 1
                if depth == 0:
                    found.append(keys)
                    break
            elif (depth == 1 and kind in ("name", "text") and tokens[i - 1][0] in ("{", ",")
                  and i + 2 < len(tokens) and tokens[i + 1][0] == ":" and tokens[i + 2][0] == "text"):
                keys[text] = tokens[i + 2][1]
    return found


def _json_arguments(text):
    try:
        args = json.loads(text)
    except ValueError:
        return []
    return [args] if isinstance(args, dict) else []


def _escalation(payload):
    """The arguments of a call that asks to leave the sandbox, or None."""
    what, name = payload.get("type"), payload.get("name")
    if what == "function_call" and name == "exec_command":
        text, read = payload.get("arguments"), _json_arguments
    elif what == "custom_tool_call" and name == "exec":
        text, read = payload.get("input"), _script_arguments
    else:
        return None
    if not isinstance(text, str) or "require_escalated" not in text or len(text) > MAX_ARGUMENTS:
        return None
    return next((args for args in read(text) if args.get("sandbox_permissions") == "require_escalated"), None)


def _calls(state, rec, payload):
    """Calls that ask to leave the sandbox, and have no output yet.

    A request for approval is not written to the rollout (`policy.rs`: it is a
    transient event), but the call it is about is, and its output comes only
    after the person has decided. Only those calls are kept, by their id.
    """
    what, cid = payload.get("type"), payload.get("call_id")
    if not isinstance(cid, str):
        return
    calls = state["calls"]
    if what in ("function_call_output", "custom_tool_call_output"):
        calls.pop(cid, None)
        return
    args = _escalation(payload)
    if args is not None:
        calls[cid] = (_ms(rec.get("timestamp")), _command(args))
        for old in list(calls)[:-MAX_CALLS]:
            del calls[old]


def _asked(state):
    """The call the person is probably being asked about, as (when, command), or None.

    Believed only of a session that can ask (a policy of `never` answers such a
    call at once, with a refusal) and only inside a turn: whatever the turn left
    unanswered is gone with it. The oldest wins, as it would be asked first.
    """
    if state["status"] != "busy" or state["policy"] in ("", "never") or not state["calls"]:
        return None
    return next(iter(state["calls"].values()))


# The account's usage limit outlives the run that hit it, so it is looked for on
# disk: in the newest finished turn of the rollouts of the last few days.
LIMIT_DAYS = 8
LIMIT_FILES = 60
LIMIT_EVERY = 10.0         # seconds between two looks


def _blank_done():
    return {"offset": 0, "ino": None, "head": b"", "done": None}


def _absorb_done(state, text):
    """Of a rollout, only the last turn that finished: when, and in what error."""
    for line in text.splitlines():
        if '"task_complete"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        payload = rec.get("payload") if isinstance(rec, dict) else None
        if (isinstance(payload, dict) and rec.get("type") == "event_msg"
                and payload.get("type") == "task_complete" and _ms(rec.get("timestamp"))):
            state["done"] = (_ms(rec.get("timestamp")), _failure(payload.get("error"), rec.get("timestamp")))
    return state


def _numbered(folder):
    """The sub-folders of `folder` named for a number, the highest first."""
    try:
        names = [e.name for e in os.scandir(folder) if e.name.isdigit() and e.is_dir()]
    except OSError:
        return []
    return sorted(names, reverse=True)


def _recent_days(root, count):
    """The `count` newest day folders of `sessions/YYYY/MM/DD`."""
    days = []
    for year in _numbered(root):
        for month in _numbered(root / year):
            for day in _numbered(root / year / month):
                days.append(root / year / month / day)
                if len(days) == count:
                    return days
    return days


def _source(value):
    """A thread's `source` as one word. Most are a word (`exec`, `cli`); a
    subagent's thread carries an object, `{"subagent": "review"}` (the thread
    table keeps it as that object's text), and is told by the subagent's
    name. Anything else is no word at all."""
    if isinstance(value, str) and value.startswith("{"):
        try:
            value = json.loads(value)
        except ValueError:
            return ""
    if isinstance(value, dict):
        value = value.get("subagent")
    return value if isinstance(value, str) else ""


def _blank():
    return {**minutes.blank_counts(), "status": "", "statusAt": 0,
            "said": "", "prompt": "", "cwd": "", "startedAt": 0, "source": "",
            "failure": None, "policy": "", "calls": {}, "review": False}


def _absorb(state, text):
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        minutes.count(state, rec)
        kind, payload = rec.get("type"), rec.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if kind == "session_meta":
            state["cwd"] = payload.get("cwd") or state["cwd"]
            state["source"] = _source(payload.get("source")) or state["source"]
            state["startedAt"] = _ms(rec.get("timestamp")) or state["startedAt"]
            continue
        if kind == "turn_context":
            how = payload.get("approval_policy")
            state["policy"] = how if isinstance(how, str) else ""
            continue
        if kind == "response_item":
            _calls(state, rec, payload)
            continue
        if kind != "event_msg":
            continue
        what = payload.get("type")
        if what == "task_started":
            state["status"], state["statusAt"] = "busy", _ms(rec.get("timestamp"))
            state["failure"] = None
            state["calls"].clear()
        elif what in ("task_complete", "turn_aborted"):
            state["status"], state["statusAt"] = "idle", _ms(rec.get("timestamp"))
            if what == "task_complete":
                state["failure"] = _failure(payload.get("error"), rec.get("timestamp"))
        elif what == "entered_review_mode":
            state["review"] = True
        elif what == "agent_message" and isinstance(payload.get("message"), str):
            state["said"] = payload["message"]
        elif what == "user_message" and isinstance(payload.get("message"), str):
            # Your next prompt ends the turn that said something.
            state["prompt"], state["said"] = payload["message"], ""
    minutes.prune(state)
    return state


def _cold(state, path):
    """A big rollout's first sight read only its tail: the minutes before it are not known."""
    minutes.cold_counts(state)


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
        self.tail = Tailed(_blank, _absorb, _cold)
        self.done_tail = Tailed(_blank_done, _absorb_done)
        self.clock = time.time
        self.held = None       # the account's usage limit, as `limit()` says it
        self.looked = None     # when it was last looked for
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
        now = self.clock()
        quiet = None
        if path:
            try:
                quiet = (now - path.stat().st_mtime) / 60
            except OSError:
                quiet = None
        row = row or {}
        source = state["source"] or _source(row.get("source")) or ""
        started = state["startedAt"] or (row.get("createdAt") or 0)
        title = " ".join((row.get("title") or "").split())
        if len(title) > TITLE_LEN:
            title = title[:TITLE_LEN - 1].rstrip() + "…"
        extras = {}
        if row.get("model"):
            extras["model"] = str(row["model"])
        if isinstance(row.get("tokens"), int) and row["tokens"] > 0:
            extras["tokens"] = f"{row['tokens'] / 1000:.0f}k"
        asked = _asked(state)
        out = {
            "id": tid,
            "cwd": state["cwd"] or row.get("cwd") or "",
            # No status event yet -- a fresh session before its first turn --
            # is idle since it started. One waiting on an approval says so.
            "status": "waiting" if asked else state["status"] or "idle",
            "updatedAt": (asked[0] if asked else state["statusAt"]) or state["statusAt"] or started,
            "startedAt": started,
            "kind": KINDS.get(source, "review" if "review" in source else source or "?"),
            "branch": row.get("branch") or "",
            "title": title,
            "prompt": state["prompt"],
            "said": state["said"],
            "quietFor": quiet,
            # What the last turn ended in, if it was an error: Limit or Error.
            "failure": state["failure"],
            # Records per minute, 30 of them: what the project's graph is made of.
            # A session with no rollout yet has none to count, which is not zero.
            "writes": minutes.strip(state, now) if path else None,
            # Codex writes nothing to its rollout while a command runs, and
            # nothing here looks at what runs under the session: silence is
            # not known to be silence, so the core must not call it Hung. A
            # pending escalated command is not Hung either: it is Needs you.
            "procsUnknown": True,
            "extras": extras,
        }
        if asked:
            out["asking"] = {"kind": "permission", "tool": "Shell", "command": asked[1], "target": ""}
        if out["kind"] in RUNS:
            # A one-shot: somebody started it, and the processes above it say who.
            out["run"] = "codex review" if state["review"] or out["kind"] == "review" else "codex exec"
            out["ancestors"] = procs.ancestors(self.proc, held[0]) if held else []
            task = procs.task_above(self.proc, held[0], out["ancestors"]) if held else None
            if task:
                out["task"] = task
        if held:
            out["pid"] = held[0]
        return out

    def _limit(self):
        """The account's usage limit, or None: the newest finished turn of the
        recent rollouts is a refusal. A file's modified time is when it last
        wrote, so once the next one is older than the newest finished turn
        found, none after it can hold a newer."""
        files = []
        for day in _recent_days(self.home / "sessions", LIMIT_DAYS):
            try:
                entries = list(os.scandir(day))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.name.startswith("rollout-") and entry.name.endswith(".jsonl") and entry.is_file():
                        files.append((entry.stat().st_mtime, entry.path))
                except OSError:
                    continue
        files.sort(reverse=True)
        newest, looked = None, set()
        for mtime, path in files[:LIMIT_FILES]:
            if newest and mtime + 1 < newest[0] / 1000:
                break
            looked.add(("state", path))
            done = self.done_tail.scan(Path(path))["done"]
            if done and (newest is None or done[0] > newest[0]):
                newest = done
        self.done_tail.cache = {k: v for k, v in self.done_tail.cache.items() if k in looked}
        if newest and newest[1] and newest[1]["kind"] == "limit":
            return {"name": "Codex", "at": newest[0], "resetsAt": newest[1]["resetsAt"]}
        return None

    def limit(self):
        return self.held

    def live(self):
        now = self.clock()
        if self.looked is None or not 0 <= now - self.looked < LIMIT_EVERY:
            self.looked = now
            try:
                self.held = self._limit()
            except OSError:         # a rollout went while it was looked at: the next look will see
                self.held = None
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
