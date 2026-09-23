"""What a provider is, and the helpers every provider gets for free.

A provider answers one question -- which of its sessions are alive right now,
and how each one is doing -- as a list of plain dicts. The core turns those
facts into the rows the page draws. How a provider knows is its own business:
Claude Code keeps peer files with a pid, Codex holds a lock file open, a
future one may have to ask an HTTP server.

Required on every session: `id` (stable within the provider), `cwd`,
`status` (`busy` | `idle` | `waiting`) and `updatedAt` -- milliseconds epoch
of the moment the status last changed, not the last activity. The global
key is `provider:id`, so a provider name may not contain a colon.

Optional: `pid`, `name`, `branch`, `title`, `prompt`, `said` (the raw text of
the last thing the agent said -- the core shapes it), `waitingFor`,
`startedAt`, `kind`, `tmux`, `bg`, `routine`, `boss`, `team`, `paths`,
`doing`, `quietFor`, `toolFor`, `canJump`, `extras`.
"""
import os

# What a provider can know. Two of these change what the core does: without
# `waiting` the chime never rings for that provider; without `jump` no row of
# its is clickable to raise a terminal. The other three say whether a missing
# field is data that is absent or data that will never exist.
CAPABILITIES = frozenset({"jump", "branch", "waiting", "name", "status"})
STATUSES = ("busy", "idle", "waiting")


class Provider:
    name = ""                     # "claude", "codex" -- no colon
    capabilities = frozenset()

    def live(self):
        """The sessions alive now, as a list of dicts. Never called twice at once."""
        raise NotImplementedError

    def find(self, session_id):
        """One live session by id, or None. Called on a click, so cheap wins.

        The default asks `live()` and picks. A provider that can answer
        without building the whole list should.
        """
        for s in self.live():
            if isinstance(s, dict) and s.get("id") == session_id:
                return s
        return None

    def jump(self, session):
        """Raise this session's terminal. None means: use the pid and `jump.py`.

        A provider that implements it returns {"ok": bool, "reason": str}.
        """
        return None


# ------------------------------------------------------------- processes

def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


# How the kernel numbers a `/dev/pts/*`: this major, plus a minor for the
# window. The whole field is 0 when a process has no terminal at all.
PTS_MAJOR = 136


def controlling_tty(pid, proc="/proc"):
    """The process's controlling terminal, as the kernel numbers it.

    0 means it has none. `None` means `/proc` would not say, which is not
    the same answer and must not be read as one.

    It comes from the seventh field of `/proc/<pid>/stat` rather than from
    `fd/0`, because stdin lies. A session whose window is gone still holds
    the `/dev/pts/21` it inherited, and that number has since been handed
    to somebody else's window.
    """
    try:
        with open(os.path.join(proc, str(int(pid)), "stat"), encoding="utf-8") as fh:
            stat = fh.read()
    except (OSError, TypeError, ValueError):
        return None
    try:
        # The command sits in parentheses and may itself contain spaces and
        # parentheses, so the fields are counted from the last one.
        return int(stat[stat.rindex(")") + 2:].split()[4])
    except (ValueError, IndexError):
        return None


def on_a_terminal(pid, proc="/proc"):
    tty = controlling_tty(pid, proc)
    return bool(tty) and (tty >> 8) & 0xfff == PTS_MAJOR


# ------------------------------------------------------ incremental files

HEAD_BYTES = 256
COLD_BYTES = 2_000_000   # enough tail to answer 'what is it doing now'


def read_from(path, offset):
    """Bytes appended since `offset`, up to the last complete line.

    A session may be mid-write, so the final fragment is left for next time
    rather than parsed as a broken record.
    """
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    return data[:cut].decode("utf-8", errors="ignore"), offset + cut


def head_of(path):
    """The first bytes of the file, as a cheap identity for its contents."""
    try:
        with path.open("rb") as fh:
            return fh.read(HEAD_BYTES)
    except OSError:
        return b""


class Tailed:
    """Read an append-only file once from its tail, then only what is new.

    Transcripts reach tens of megabytes and the busy ones change every few
    seconds. Re-reading them whole on every poll cost ~9 seconds a round and
    made clicking feel broken. `blank()` makes a fresh state, `absorb(state,
    text)` folds new lines into it, and `cold(state, path)` runs once after
    the first sight of a large file, for whatever the tail cannot answer.
    """

    def __init__(self, blank, absorb, cold=None):
        self.blank, self.absorb, self.cold = blank, absorb, cold
        self.cache = {}

    def scan(self, path):
        try:
            stat = path.stat()
        except OSError:
            return self.blank()
        key = ("state", str(path))
        state = self.cache.get(key)
        head = head_of(path)
        # Same inode and a file that only grew is the normal case. A shrunken
        # file or a changed opening means it was rewritten, and what we
        # remember about it is about a file that no longer exists.
        # A file shorter than HEAD_BYTES grows its own head as it is appended
        # to, so one being a prefix of the other still means the same file.
        same_file = (state is not None
                     and state["ino"] == stat.st_ino
                     and stat.st_size >= state["offset"]
                     and (head.startswith(state["head"])
                          or state["head"].startswith(head)))
        if not same_file:
            state = self.blank()          # new file, or rewritten from the top
            state["offset"], state["ino"] = 0, stat.st_ino
        state["head"] = head
        if state["offset"] == 0 and stat.st_size > COLD_BYTES:
            # First sight of a large file. Every value is a *latest* one, so
            # the tail answers them; what it cannot, `cold` reads once.
            text, offset = read_from(path, stat.st_size - COLD_BYTES)
            state = self.absorb(state, text)
            state["offset"] = offset
            if self.cold:
                self.cold(state, path)
        elif stat.st_size > state["offset"]:
            text, offset = read_from(path, state["offset"])
            state = self.absorb(state, text)
            state["offset"] = offset
        self.cache[key] = state
        return state
