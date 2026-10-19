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

`cwd` is the folder the session was launched in, not where it is now: the
project a session belongs to is decided by it, and a session that `cd`s
elsewhere must stay where it started.

Optional: `pid`, `name`, `branch`, `title`, `prompt`, `said` (the raw text of
the last thing the agent said -- the core shapes it), `waitingFor`,
`startedAt`, `kind`, `tmux`, `bg`, `routine`, `boss`, `track` (a boss's
track: the name of its tracker), `team`, `paths`, `doing`, `quietFor`,
`toolFor`, `canJump`, `attach`, `noJump`, `extras`, `asking`, `failure`,
`lastTool`, `procsUnknown`, `shellCpuAgo`, `turnOver`.

`canJump` says a pane shows the session. `attach` is what to attach to when no
pane does but a new tab can show it (a background session; the provider's own
`jump` does the attaching). `noJump` is why neither, when the provider has more
to say than "no terminal".

`asking` is what the session is stopped on right now, or absent. Four shapes:
`{"kind": "question", "questions": [{"question", "header", "multi",
"options": [{"label", "description"}]}]}` for an open question (`questions`
is `[]` when the dialog is open and its text is not written yet), and
`{"kind": "permission", "tool", "command", "target"}` for an open permission
prompt. `command` is present only when the prompt is for a shell command
(`COMMAND_LIMIT` characters, plus one if it was cut); `target` names a file or
address for any other tool. The third, `{"kind": "request", "what"}`, is any
other dialog that waits on the person's answer or approval (a sandbox asking
for the network, a goal proposed), told by `what`, the provider's own name for
it. A fourth, `{"kind": "pause", "what"}`, is a session paused on usage
credits: a dialog that waits on a choice, but the usage limit is what holds the
session, so the core reads it as a Limit and not as Needs you. A menu or panel
the person opened themselves is not `asking` at all. The provider decides what
is open; the core only prints what it is told.

`failure` is an API error that is the newest thing the session said, or absent:
`{"kind": "limit" | "error", "type", "status", "text", "at", "resetsAt"}`. The
provider decides which it is (a rate limit is `limit`, any other API or auth
error `error`); `type` is the error's own name, `status` its HTTP status or
None, `text` the words it carries, `at` and `resetsAt` milliseconds since 1970
(`resetsAt` None when the error names no reset time). It is gone once the
model answers or the person types something -- not when the session merely
writes bookkeeping of its own or a reply Claude Code wrote itself with no model
call, and not for a notification or a message from another session, which call
no model while the error holds -- so a provider must clear it itself.

`lastTool` is the newest call the session made, answered or not:
`{"text", "at"}`, said the way `doing` is, with `at` in milliseconds.

`procsUnknown` is True when the provider looked for what runs under a busy
session and could not tell (the process folder would not answer, or this was
the first look at a command, with nothing to compare its CPU with). Then an
absence of `bgTasks` and `shellCpu` is not evidence of absence, and the core
does not call the session hung. A provider that cannot look at all says True
every time; leaving it out says the look was made and found nothing.

`shellCpuAgo` is how many minutes ago CPU was last seen moving under a command
the session is waiting on (the same look that makes `shellCpu`), or None when
it never was while the provider watched. Not moving for `hung_after_minutes` is
counted from the youngest sign of life, and a command whose CPU moved a minute
ago is one.

`turnOver` is True when the session's own last word ended its turn although it
still says `busy`: some agents go on saying so for as long as their helpers
live. A turn ends with a turn-end record, or with an API error as the reply,
and a compaction of the session does not open it again; nor does anything that
calls no model while the error holds (a notification, a message from another
session). Such a session has
nothing running of its own, so the core never calls it hung; it moves only
while a subagent writes. Leaving it out, or anything but True, says the status
is believed.
"""
import os

# What a provider can know. Two of these change what the core does: without
# `waiting` the chime never rings for that provider; without `jump` no row of
# its is clickable to raise a terminal. The other three say whether a missing
# field is data that is absent or data that will never exist.
CAPABILITIES = frozenset({"jump", "branch", "waiting", "name", "status"})
STATUSES = ("busy", "idle", "waiting")

# The longest command a provider hands over whole. A permission prompt's
# command is copied from the page, and a cut one must not be copied: the
# provider sends one character more than this when it had to cut.
COMMAND_LIMIT = 4000

# How much of a dialog a tile can hold. The reader keeps no more than this of
# what a session wrote into a question, and the core cuts to it again.
MAX_QUESTIONS = 4        # what AskUserQuestion allows
MAX_OPTIONS = 6
QUESTION_LEN = 600
LABEL_LEN = 120
HINT_LEN = 240
FAILURE_LEN = 200        # what an API error says, as much as a tile holds

# The latest time a field in milliseconds can name (the year 5000). Anything
# beyond it is a number that is not a time.
MAX_MS = 95_000_000_000_000


def whole_number(value):
    """The value if it is a whole number -- an int, and a bool is not one -- else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def milliseconds(value, seconds=False):
    """A time as whole milliseconds since 1970, or None if the value is not one.
    `seconds` says the number counts seconds, the way some of Claude Code's
    fields do. A time is a positive number below the year 5000; the checks are
    comparisons because they hold for any number, where `isfinite` raises on an
    int too big for a float and NaN and infinity fail them without help."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    ms = value * 1000 if seconds else value
    return int(ms) if 0 < ms < MAX_MS else None


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
