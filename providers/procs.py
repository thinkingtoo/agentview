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
import time

SHELL_MARK = b"shell-snapshots"

# A shell can start a thousand things. Looking at more than this costs more
# than it can tell.
MAX_WALK = 200

# Seconds. CPU is a difference between two looks, so a look is only a baseline
# while it is recent: the poll comes every few seconds, and a session that was
# not looked at for an hour has no baseline at all.
STALE = 10.0

# How long CPU counts as seen after the last tick moved. A download or a test
# that waits on disk burns nothing for a second or two between bursts, and the
# sign on the tile should not blink with it.
GRACE = 15.0


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


def _stat(proc, pid):
    """(start time, CPU ticks used so far) of a process, or None.

    The command in the second field sits in parentheses and may contain
    spaces and parentheses of its own, so the fields are counted from the
    last one.
    """
    raw = _read(f"{proc}/{pid}/stat")
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        fields = text[text.rindex(")") + 2:].split()
        return int(fields[19]), int(fields[11]) + int(fields[12])
    except (ValueError, IndexError):
        return None


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

    def look(self, pid, now=None):
        """{"shells": how many commands it is running, "cpu": whether any of
        them, or anything they started, used CPU since the last look}, or
        None when `/proc` cannot say."""
        now = time.time() if now is None else now
        kids = _children(self.proc, pid)
        if kids is None:
            return None
        shells = [k for k in kids
                  if SHELL_MARK in (_read(f"{self.proc}/{k}/cmdline") or b"")]
        walked, queue, seen, moved = set(), list(shells), {}, False
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
            if before and 0 <= now - before[1] <= STALE and ticks > before[0]:
                moved = True
            queue.extend(_children(self.proc, at) or [])
        self.last = {key: value for key, value in {**self.last, **seen}.items()
                     if now - value[1] <= STALE * 6}
        if moved:
            self.cpu_at[pid] = now
        self.cpu_at = {p: t for p, t in self.cpu_at.items() if now - t <= GRACE}
        return {"shells": len(shells), "cpu": pid in self.cpu_at}
