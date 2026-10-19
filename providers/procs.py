"""The commands a session is running, and whether any of them is using CPU.

A Claude Code session runs every command it starts through a shell of its
own: a direct child of the session whose command line names the session's
`shell-snapshots`. Those shells, and what they start, are the only processes
that can be the thing a session is waiting on. Everything else under it (the
MCP servers, their helpers) runs whether or not the session does anything, and
counting them would make a session look alive for as long as its tools are.

Nothing here guesses. A process that exits mid-walk, one that is not ours to
read, a `stat` that makes no sense: each is the absence of evidence, never
evidence. The caller gets `None` when `/proc` cannot answer at all.
"""
import os
import time

SHELL_MARK = b"shell-snapshots"

# A shell can start a thousand things. Looking at more than this costs more
# than it can tell.
MAX_WALK = 200

# Seconds. CPU is a difference between two looks, so a look is only a baseline
# while it is recent: the poll comes every few seconds, and a session that was
# not looked at for an hour has no baseline at all.
STALE = 10.0

# How long a look is remembered at all. Longer than a poll can be late.
FORGET = STALE * 6

# How long CPU counts as seen after the last tick moved. A download or a test
# that waits on disk burns nothing for a second or two between bursts, and the
# sign on the tile should not blink with it.
GRACE = 15.0

# How long it is remembered that CPU moved at all, for `cpu_ago`. The core
# counts a command as a sign of life for six hours at most (`WAIT_MAX_MINUTES`),
# so what happened before that is never asked about.
CPU_MEMORY = 6 * 3600.0


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None             # gone, or not ours to read: unknown either way


def _children(proc, pid):
    """The children of a process's main thread, or None if `/proc` will not
    say (it needs CONFIG_PROC_CHILDREN, and the process may be gone)."""
    raw = _read(f"{proc}/{pid}/task/{pid}/children")
    if raw is None:
        return None
    try:
        return [int(token) for token in raw.split()]
    except ValueError:
        return None


def _task_of(proc, pid):
    """The id of the background task whose output file this process writes to
    as its standard output, or None.

    A background command runs in a shell of its own with stdout on
    `.../tasks/<id>.output`, so the id ties a task in the transcript to the
    very process running it. A shell that belongs to something else has some
    other output, and cannot stand in for it.
    """
    try:
        target = os.readlink(f"{proc}/{pid}/fd/1")
    except OSError:
        return None             # the descriptor is gone, or not ours to read
    folder, name = os.path.split(target)
    if name.endswith(".output") and os.path.basename(folder) == "tasks":
        return name[:-len(".output")]
    return None


def _fields(proc, pid):
    """The fields of a process's `stat` after its command, or None.

    The command in the second field sits in parentheses and may contain
    spaces and parentheses of its own, so the fields are counted from the
    last one.
    """
    raw = _read(f"{proc}/{pid}/stat")
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        return text[text.rindex(")") + 2:].split()
    except ValueError:
        return None


def _stat(proc, pid):
    """(start time, CPU ticks used so far) of a process, or None."""
    fields = _fields(proc, pid)
    try:
        return int(fields[19]), int(fields[11]) + int(fields[12])
    except (TypeError, ValueError, IndexError):
        return None


# How far up the walk goes. A shell inside a terminal inside a window manager is
# ten levels at most; a longer chain is a loop or a runaway, not an answer.
MAX_UP = 64


def _parent(proc, pid):
    """(parent pid, start time) of a process, or None."""
    fields = _fields(proc, pid)
    try:
        return int(fields[1]), int(fields[19])
    except (TypeError, ValueError, IndexError):
        return None


def ancestors(proc, pid):
    """The processes above `pid`, nearest first, init left out: who started it.

    The walk goes up one parent at a time and ends, with what it has, at the
    first thing it cannot vouch for -- never at a guess:

    - a parent that is gone, or not ours to read;
    - a parent that started after its child, which is a number the kernel
      handed to somebody else once the real parent had exited;
    - a child whose own parent changed while the parent was being read, which
      is the same exit seen from the other side;
    - a process met twice (a loop), and a walk longer than `MAX_UP`.
    """
    if not isinstance(pid, int) or pid <= 1:
        return []
    at, found = pid, []
    here, seen = _parent(proc, at), {pid}
    while here is not None and len(found) < MAX_UP:
        parent, start = here
        if parent <= 1 or parent in seen:
            break
        above = _parent(proc, parent)
        if above is None or above[1] > start or _parent(proc, at) != here:
            break
        found.append(parent)
        seen.add(parent)
        at, here = parent, above
    return found


class Shells:
    """Looks under session pids and remembers the last look at each process.

    A process is known by its pid and its start time together: a pid the
    kernel hands to a new process has a new start time, so what the old one
    had used is not a baseline for it.
    """

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.last = {}          # (pid, start time) -> (ticks, when looked)
        self.cpu_at = {}        # session pid -> when CPU was last seen moving
        self.cpu_seen = {}      # the same, kept for CPU_MEMORY: `cpu_at` is the flicker guard

    def look(self, pid, now=None):
        """{"shells": how many commands it is running, "cpu": whether any of
        them, or anything they started, used CPU since the last look, "tasks":
        the background tasks whose shells are alive}, or None when `/proc`
        cannot say.

        "cpu" is None, not False, when it cannot be said yet: the first look at
        a command (every session is, after a restart), or a walk that could
        read none of what it found. "Uses none" is a claim, and it takes a
        look to compare with."""
        now = time.time() if now is None else now
        kids = _children(self.proc, pid)
        if kids is None:
            return None
        shells = [k for k in kids
                  if SHELL_MARK in (_read(f"{self.proc}/{k}/cmdline") or b"")]
        walked, queue, seen, moved = set(), list(shells), {}, False
        # With no command running there is nothing whose CPU could be
        # compared, and that is a complete answer.
        based = not shells
        while queue and len(walked) < MAX_WALK:
            at = queue.pop()
            if at in walked:
                continue
            walked.add(at)
            got = _stat(self.proc, at)
            if got is None:
                continue
            start, ticks = got
            seen[(at, start)] = (ticks, now)
            before = self.last.get((at, start))
            if before and 0 <= now - before[1] <= STALE:
                based = True
                moved = moved or ticks > before[0]
            queue.extend(_children(self.proc, at) or [])
        self.last = {key: value for key, value in {**self.last, **seen}.items()
                     if now - value[1] <= FORGET}
        if moved:
            self.cpu_at[pid] = now
            self.cpu_seen[pid] = now
        self.cpu_at = {p: t for p, t in self.cpu_at.items() if now - t <= GRACE}
        self.cpu_seen = {p: t for p, t in self.cpu_seen.items() if now - t <= CPU_MEMORY}
        tasks = [t for t in (_task_of(self.proc, shell) for shell in shells) if t]
        cpu = True if pid in self.cpu_at else (False if based else None)
        return {"shells": len(shells), "cpu": cpu, "tasks": tasks}

    def cpu_ago(self, pid, now=None):
        """Minutes since a look saw CPU moving under this session, or None when
        none did (or not for `CPU_MEMORY`). `look` says whether it moves now;
        this says how long ago it last did, for a session that has gone quiet.
        Kept apart from `look`, whose answer is exactly three keys."""
        seen = self.cpu_seen.get(pid)
        if seen is None:
            return None
        now = time.time() if now is None else now
        return max(0.0, (now - seen) / 60)


def task_above(proc, pid, above):
    """The id of the background task that holds `pid`, or None: the first of `pid`
    and the processes above it, nearest first, whose standard output is a task's
    output file (see `_task_of`).

    A command a session runs in the background has its shell write to that file,
    and whatever the command starts sits below the shell -- or is the shell, when
    it ran the command in its own place. So a run knows which of its starter's
    tasks it is. A process that is gone or not ours to read says nothing and the
    next one is asked.
    """
    if not isinstance(pid, int) or pid <= 1:
        return None
    chain = [pid] + [p for p in (above if isinstance(above, list) else ())[:MAX_UP]
                     if isinstance(p, int) and p > 1]
    for at in chain:
        task = _task_of(proc, at)
        if task:
            return task
    return None
