#!/usr/bin/env python3
# vendored from cc-agent-names@11c70db -- do not edit, run scripts/vendor-registry
"""Claude Code's session registry: which sessions are alive, and their records.

Claude Code publishes one peer file per running session,
`$CLAUDE_CONFIG_DIR/sessions/<pid>.json`. It writes the file when a session
starts and does not always remove it when the session ends, so a file that
exists says only that a session *was* there.

A session is live when all of these hold:

- its pid exists;
- `/proc/<pid>/stat` field 22 (the start time) equals the record's
  `procStart`, so a pid the kernel has handed to another process does not
  count. A record without `procStart` is not live;
- the process is not a zombie;
- a session started from a terminal (`entrypoint == "cli"`) still has a
  controlling terminal. Closing the window orphans the process rather than
  ending it, and an orphan answers every other test like a working session.

A stopped process (Ctrl-Z) is live: its terminal is still there.

Records are returned as Claude Code wrote them, plus `path`. This module only
reads; it never writes or deletes a peer file.

Used as a CLI from shell scripts:

    registry.py live            one JSON record per line
    registry.py by-sid SID      the record, or exit 1
    registry.py by-pid PID      the record, or exit 1
    registry.py own             the record of the session this runs under

Vendored into agentview and claude-boss; the master copy is in cc-agent-names.
"""
import json
import os
import re
import sys
from pathlib import Path


def config_dir(cfg=None):
    if cfg is not None:
        return Path(cfg)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _stat(pid, proc):
    """The fields after the command in /proc/<pid>/stat, or None."""
    try:
        text = (Path(proc) / str(int(pid)) / "stat").read_text(encoding="utf-8")
        # The command sits in parentheses and may itself hold spaces and
        # parentheses, so the fields are counted from the last one.
        return text[text.rindex(")") + 2:].split()
    except (OSError, TypeError, ValueError):
        return None


def records(cfg=None):
    """Every peer file that parses, live or not."""
    for path in sorted((config_dir(cfg) / "sessions").glob("*.json")):
        rec = _read(path)
        if rec is not None:
            yield rec


def is_live(rec, proc="/proc"):
    fields = _stat(rec.get("pid"), proc)
    if not fields or len(fields) < 20:
        return False
    if not rec.get("procStart") or fields[19] != str(rec["procStart"]):
        return False
    if fields[0] == "Z":
        return False
    if rec.get("entrypoint") == "cli" and fields[4] == "0":
        return False
    return True


def live(cfg=None, proc="/proc"):
    return [rec for rec in records(cfg) if is_live(rec, proc)]


def _read(path):
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    rec["path"] = str(path)
    return rec


def by_pid(pid, cfg=None):
    """The peer file named after this pid, live or not, or None."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return _read(config_dir(cfg) / "sessions" / f"{pid}.json")


def by_sid(session_id, cfg=None, proc="/proc"):
    """The record for a session id, live or not, or None.

    Files are named by pid, so this reads them all. A resumed session gets a
    new pid while the old file may linger with the same id; the live record
    wins.
    """
    found = None
    for rec in records(cfg):
        if rec.get("sessionId") != session_id:
            continue
        if is_live(rec, proc):
            return rec
        found = found or rec
    return found


def own(pid=None, cfg=None, proc="/proc", env=None):
    """The record of the session this process runs under, or None.

    The parents are walked up to the first pid with a peer file: a hook, a
    tool call and a script it starts all sit somewhere below their session's
    `claude` process. When nothing up there has one, Claude Code's own
    `CLAUDE_CODE_SESSION_ID` is asked.
    """
    pid = os.getpid() if pid is None else int(pid)
    for _ in range(32):
        rec = by_pid(pid, cfg)
        if rec is not None:
            return rec
        fields = _stat(pid, proc)
        if not fields:
            break
        pid = int(fields[1])
        if pid <= 1:
            break
    sid = (os.environ if env is None else env).get("CLAUDE_CODE_SESSION_ID")
    return by_sid(sid, cfg, proc) if sid else None


def _encode(cwd):
    # Claude Code files transcripts under the cwd with every character that is
    # not a letter or a digit turned into a dash: ~/.claude -> -home-u--claude.
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def transcript_of(rec, cfg=None):
    """The path of a session's transcript, or None.

    The direct path is one stat away. A session whose cwd moved after it
    started is filed under the old one, so it is looked for wider.
    """
    sid = rec.get("sessionId")
    if not sid:
        return None
    projects = config_dir(cfg) / "projects"
    direct = projects / _encode(rec.get("cwd") or "") / f"{sid}.jsonl"
    if direct.is_file():
        return direct
    for hit in projects.glob(f"*/{sid}.jsonl"):
        return hit
    return None


def main(argv):
    cmd, arg = (argv + [None, None])[:2]
    if cmd == "live":
        for rec in live():
            print(json.dumps(rec))
        return 0
    if cmd == "by-sid" and arg:
        rec = by_sid(arg)
    elif cmd == "by-pid" and arg:
        rec = by_pid(arg)
    elif cmd == "own":
        rec = own(pid=os.getppid())
    else:
        print(__doc__.split("Used as a CLI")[1].split("Vendored")[0].strip(), file=sys.stderr)
        return 2
    if rec is None:
        return 1
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
