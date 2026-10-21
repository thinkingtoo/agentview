"""Which words in a session's line are a command for the person to run.

The session-line hook writes `ask` as free text, so this is a guess, and it
errs towards offering too little: a missing button costs a selection with the
mouse, a button on a sentence costs the person's trust in every other button.
The rule that follows from it is that the text offered is always text the
session wrote as one whole command. Where that cannot be told -- a command
after a `$` with more words behind it, a command inside a quote that holds
another, a quote that was never closed -- nothing is offered.
"""
import re
from typing import NamedTuple

# Where a quote may open and where it may close. One glued to a word or to an
# `=` belongs to an argument (`--title="x"`, `MAPLE_ENV="prod"`), and one that
# follows another quote is nested in it: neither is the edge of a phrase.
OPENS = r"(?<![^\s(\[{:;,\u2014\u2013\u00ab\u201c\u2018\u2026])"
CLOSES = r"(?=$|[\s.,;:!?)\]}\u2026\u2014\u2013\u00bb\u201d\u2019])"
# Every way a session quotes something, and for the straight marks the mark
# itself. A single quote is also an apostrophe: one only opens a quote at the
# start of a word and closes it at the end of one, so "don't" and "the owner's
# call" never pair up. A backslash keeps the quote it escapes inside the quote.
QUOTES = (
    (re.compile(OPENS + r'"((?:\\.|[^"\\\n])+)"' + CLOSES), '"'),
    (re.compile(OPENS + r"`((?:\\.|[^`\\\n])+)`" + CLOSES), "`"),
    (re.compile(OPENS + r"'([^'\n]+)'" + CLOSES), "'"),
    (re.compile(r"\u201c([^\u201d\n]+)\u201d"), None),
    (re.compile(r"\u00ab([^\u00bb\n]+)\u00bb"), None),
    (re.compile(r"(?<!\w)\u2018([^\u2019\n]+)\u2019(?!\w)"), None),
)
# A mark that no pair claims, outside every claimed region, means the pairing
# cannot be trusted: a line cut inside a quote, a quote never closed, a mark the
# session forgot. A quote left open may hold the quotes of every other kind, so
# with one on the line nothing quoted is offered. An apostrophe at the end of a
# word (`users'`, `po'`) is a weaker sign: only the single quotes are doubted.
STRONG_STRAY = re.compile(r"""(?<!\\)["`]|[\u201c\u201d\u00ab\u00bb\u2018]|(?<!\w)'""")
WEAK_STRAY = re.compile(r"(?<=\w)'(?!\w)")
ESCAPED_QUOTE = re.compile(r"\\[\"`]")
# A quote that comes right after a flag is the argument of that flag (`sh -c
# "rm -rf x"`, `--command "sudo reboot"`), not a command of its own.
AFTER_A_FLAG = re.compile(r"(?:^|\s)--?[\w-]+\s+$")
NESTED_OPENER = re.compile(r"[\u201c\u00ab\u2018]")
# Programs that run what they are given: a quote after one of them, in the same
# clause, is meant for the other shell (`ssh maple "sudo reboot"`), not for the
# person's own.
RUNNERS = frozenset("""
ssh watch timeout xargs eval tmux docker kubectl nohup parallel runuser flock gcloud aws heroku fly
vagrant doas
""".split())
CLAUSE_END = re.compile(r"[.!?;:,]\s|[(\[{\u2014\u2013]")

# `$ ` as a shell prompt: after a space, a colon or an opening bracket (a
# backslash before the sign is a session escaping it), then a
# command word. `$5` and `$HOME` have no space after the sign, `$ 5` no command
# word, and `20 $` is an amount. A quoted argument is one unit, so the comma in `-m "one, two"`
# does not end the command; the end of the line does, so the match can never
# fail and the engine never has to try the quoted and the plain way of reading
# each quote.
DOLLAR_COMMAND = re.compile(
    r"(?<!\d)(?:^|[\s:(\[{])\\?\$ +((?:! +)?[A-Za-z./~(\[{]"
    r"(?:\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\\n])*`|(?<!\w)'[^'\n]*'(?!\w)"
    # A flag with a comma stuck to it (`-F,`) belongs to the command when a
    # quote or another flag comes after it; "-d, then tell me" is a clause.
    r"|(?<=\s)--?\w[\w-]*,(?=\s+['\"-])|[^\n])*?)"
    # Where the sentence goes on. Not every one of these ends a command (a
    # `ls .` or a quoted `, ` can look like one), which is why a command with
    # words after it is not offered at all: see COMPLETE. A period counts after
    # a word or a closing quote or bracket, or as a run of dots before a
    # capital letter, but not as part of `find .`, `cd ..` or `go test ./...`
    # (what is left of a command that ends in dots is judged by
    # `ends_in_a_stray_mark`). A `?` after a space is French typography; a `!`
    # after a space is that too at the end or before a capital letter, and
    # otherwise the shell's negation (`find ! -name x`).
    r"(?=\s\$(?:\s|$)|,\s|(?<=[\w\"'`)\]}>])\.(?:\s|$)|\.+\s+(?=[A-Z])"
    r"|(?<![\s!])[?!](?:\s|$)|\s\?(?:\s|$)|\s!(?:\s*$|\s+(?=[A-Z]))"
    r"|(?<=[\w\"'`)\]}>])(?:\*\*|__)(?=\s|$|[.,;:!?)])"
    r"|\s[\u2014\u2013]\s|\s\(|[\u00bb\u201d]|\n|$)")
# What may follow a command for it to be the whole of its line: the full stop,
# question mark or exclamation mark that ends the sentence, and the mark that
# closes a markdown bold. Another prompt does not count: what stands between
# two prompts could be an argument of the first.
COMPLETE = re.compile(r"\s*(?:\*\*|__)?[.?!]*\s*$")

PATHS = ("./", "../", "~/")
SCRIPT = re.compile(r"\.(sh|bash|py|js|mjs|rb|pl)$")
FLAG = re.compile(r"-+\w")
ENV_ASSIGNMENT = re.compile(r"[A-Z_][A-Z0-9_]*=\S*$")
# What no plain sentence has in a word: a flag, a path, a dot between letters,
# a bare number, a string, an @, an =, a shell sign. An apostrophe, a comma, a
# hyphen inside a word, an accent or a digit inside a name ("v2") are prose.
ARGUMENT_SIGN = re.compile(r"""^-+\w|^\.|^~|^\d+$|[/@=*\\|&;<>$"`]|\w\.\w""")

# What a quoted phrase has to start with to be taken for a command. A program
# the lists do not know gets no button in quotes, and that is the accepted miss.
#
# Names that are programs and also words of a sentence ("find out", "touch
# base", "rm stale notes", "pytest fixtures"): they count only when a word
# after them carries one of the signs above.
PROGRAMS = frozenset("""
ls cp mv rm mkdir chmod chown ln grep rg sed awk jq pytest ruff psql sqlite3 crontab openssl
ssh-add ssh-keygen apt-get dpkg ufw certbot
find head tail cat source export kill pkill claude codex python python3 node npx ssh scp rsync
curl wget touch echo tmux journalctl ps df du cd diff tar bash sh
""".split())
# Words that run another command: what is after them is judged by itself, so
# "sudo systemctl restart maple" is a command and "sudo access" is not.
WRAPPERS = frozenset("sudo nohup time watch".split())
# Tools with a fixed set of subcommands. "git status" is a command and "git
# history" is a title, so a plain word after them has to be one of theirs.
SUBCOMMANDS = {name: frozenset(words.split()) for name, words in {
    "git": "status log diff show add commit push pull fetch merge rebase checkout switch branch reset "
           "restore stash clone tag remote cherry-pick revert init mv rm bisect blame clean config "
           "describe grep worktree",
    "gh": "pr issue repo run workflow release api auth browse gist label",
    "docker": "build run ps up down compose exec logs pull push stop start restart images rm rmi "
              "volume network system prune login",
    "npm": "install i ci run test start build publish update uninstall init audit ls link pack version exec",
    "yarn": "install add remove run test build start dev upgrade",
    "pnpm": "install add remove run test build start dev update",
    "uv": "run sync pip add remove lock venv init tool python",
    "cargo": "build run test check fmt clippy install add publish clean doc bench update",
    "pip": "install uninstall list freeze show download check",
    "pip3": "install uninstall list freeze show download check",
    "systemctl": "start stop restart reload status enable disable daemon-reload is-active mask unmask "
                 "edit cat list-units",
    "kubectl": "get apply delete describe logs exec rollout scale port-forward config",
    "brew": "install uninstall update upgrade list search info services tap cleanup",
    "apt": "install remove update upgrade search purge autoremove",
    "ollama": "run pull list serve rm show",
    "tailscale": "up down status ip ssh serve funnel",
    # `go` has these subcommands and `make` runs a target, which is one word:
    # "make all the difference" is prose and "make test V=1" has its sign.
    "go": "build run test vet fmt mod get install generate clean env list doc work version tool",
    "make": "test build install run clean lint check fmt vet all deploy tidy dev generate docs",
}.items()}
ONE_WORD_AFTER = frozenset({"make"})

KNOWN = PROGRAMS | SUBCOMMANDS.keys() | WRAPPERS

# A command typed into a Claude pane rather than a shell. "/tmp" and "/opt" are
# folders, so a name counts when Claude Code has it built in, or when it reads
# as a plugin's skill, `plugin:skill`. Hyphenated words alone are routes too.
SLASH_BUILTINS = frozenset("""
compact autocompact clear mcp model config login logout resume init review help status cost
memory permissions hooks agents doctor plugin context rewind exit add-dir bug export
""".split())
SLASH_ARGUMENT = re.compile(ARGUMENT_SIGN.pattern + r"|\d")
SLASH_COMMAND = re.compile(r"/(?:[a-z][a-z0-9-]*:)?[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


def slash_command(word):
    """Whether `word` may name a Claude Code slash command."""
    if not SLASH_COMMAND.fullmatch(word):
        return False
    name = word[1:]
    return name in SLASH_BUILTINS or ":" in name


def reads_as_slash_command(words, prompted):
    """A slash command, judged by where it stands. A web route has the same
    shape ("/login", "/status", "/add-user"), so in quotes only a plugin's
    `plugin:skill` counts alone, and a built-in needs arguments that are no
    words of a sentence (`/compact --keep-tools`, `/autocompact 450k`). After a
    `$` the prompt already says it is something to type."""
    first, rest = words[0], words[1:]
    if not slash_command(first) or not all(SLASH_ARGUMENT.search(w) for w in rest):
        return False
    if prompted or ":" in first:
        return True
    return first[1:] in SLASH_BUILTINS and bool(rest)


class Hit(NamedTuple):
    start: int
    end: int
    command: str


def reads_as_command(text):
    """A known program, or a script run by its path, with something after it.

    One word alone is a name ("git", "./notes", "go"), not an instruction;
    the exceptions are a script named by its path ("./deploy.sh") and a Claude
    slash command ("/compact"). Claude Code's `!` prefix is looked past. A path with
    plain words after it ("~/Google Drive/My Drive") is a name that has spaces
    in it, so a path starts a command only when it names a script or a flag
    follows.
    """
    words = text.split()
    if not words:
        return False
    first, rest = words[0], words[1:]
    if first == "!":
        # Claude Code's shell prefix, once: the command is what follows it.
        return bool(rest) and rest[0] != "!" and reads_as_command(" ".join(rest))
    if first.startswith("/") and first.count("/") == 1:
        return reads_as_slash_command(words, prompted=False)
    pathlike = first.startswith(PATHS) or (first.startswith("/") and first.count("/") > 1)
    if not rest:
        return pathlike and bool(SCRIPT.search(first))
    if pathlike:
        return bool(SCRIPT.search(first)) or any(FLAG.match(w) for w in rest)
    if ENV_ASSIGNMENT.match(first):
        return reads_as_command(" ".join(rest))
    if first in WRAPPERS:
        return reads_as_command(" ".join(rest))
    if first in KNOWN and any(ARGUMENT_SIGN.search(w) for w in rest):
        return True
    return (first in SUBCOMMANDS and rest[0] in SUBCOMMANDS[first]
            and (len(rest) == 1 or first not in ONE_WORD_AFTER))


# A program of the project's own, which no list knows: lowercase words joined by
# hyphens or underscores (`maple-sync`), or a script by its name (`deploy.sh`).
# "A/B", "N/A", "and/or", "e.g." and "Node.js" are words of a sentence.
OWN_PROGRAM = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+|[a-z][\w-]*\.(?:sh|bash|py|js|mjs|rb|pl)")


def reads_as_prompted(text):
    """What follows a `$ `: the same evidence as in quotes (a subcommand, a
    sign), because `$` is also money and maths in a sentence ("the $ diff or the
    % diff", "in $ per-seat"). A path is a program by itself; a program of the
    project's own needs a script name or a sign after it."""
    words = [w for w in text.split() if w != "$"]
    if not words:
        return False
    if words[0] == "!":
        words = words[1:]
        if not words or words[0] == "!":
            return False
    first, rest = words[0], words[1:]
    if first.startswith("/") and first.count("/") == 1:
        return reads_as_slash_command(words, prompted=True)
    if first.startswith(PATHS) or (first.startswith("/") and first.count("/") > 1
                                   and re.search(r"[A-Za-z]", first) is not None):
        return True
    return reads_as_command(" ".join(words)) or (
        OWN_PROGRAM.fullmatch(first) is not None
        and (bool(SCRIPT.search(first)) or any(ARGUMENT_SIGN.search(w) for w in rest)))


# What a shell sees: a quote of any kind runs to the next one of its kind, so
# an apostrophe inside a word ("it's") opens one too.
SHELL_RUN = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\\n])*`|'[^'\n]*'")
SHELL_QUOTE = re.compile(r"[\"'`]")
CLOSERS = (("(", ")"), ("[", "]"), ("{", "}"))


def cut_or_broken(command):
    """Half a command pasted into a terminal is worse than none: the line was
    cut with an ellipsis, a quote opened in it was never closed, or it holds a
    bracket that closes something outside it ("(run $ make test)"). The shell
    takes an apostrophe inside a word ("it's") for an open quote, so it counts."""
    return (command.endswith("\u2026")
            or SHELL_QUOTE.search(SHELL_RUN.sub(" ", command)) is not None
            or any(command.count(close) > command.count(open_) for open_, close in CLOSERS))


def joins_two_commands(command):
    """`git commit --allow-empty + git push`: a `+` standing alone before the
    name of a program is the sentence's "and", so this is two commands in prose
    and pasting it runs neither."""
    words = command.split()
    return any(w == "+" and nxt in KNOWN for w, nxt in zip(words, words[1:]))


def ends_in_a_stray_mark(command):
    """A command that ends in a mark the session may have meant as part of its
    sentence: a `.` (`rm -rf ~/.cache/maple/*.`, `cd ~.`, `go test ./....`,
    `pip install -e ..`) or the `**` that closes a markdown bold
    (`rm -rf cache/***`). The dot is the command's own only as a word by itself
    (`pip install -e .`) or as Go's `/...`."""
    last = command.split()[-1]
    return ((command.endswith(".") and last != "." and not last.endswith("/..."))
            or command.endswith(("**", "__")))


def quoted_command(said):
    """The text between a pair of quotes, as a command: one a shell could take
    whole. A backtick would run what it holds, an escaped or a nested quote
    means the pairing is not the session's, and a comma or a colon at the end
    is the typography of the quote."""
    return (reads_as_command(said) and not cut_or_broken(said) and not joins_two_commands(said)
            and not ESCAPED_QUOTE.search(said) and "`" not in said
            and not NESTED_OPENER.search(said) and not said.endswith((",", ";", ":")))


def argument_of_a_runner(before):
    """Whether the words just before a quote, in the same clause, hold a
    program that runs what it is given: `ssh maple "df -h"`, `timeout 30 ssh
    maple "df -h"`, `watch -n 5 "kubectl get pods"`."""
    clause = CLAUSE_END.split(before)[-1]
    return any(w.strip("()[]{}\"'`,.:;").lower() in RUNNERS for w in clause.split()[-6:])


SHELL_PREFIX = re.compile(r"^!\s+")

# The hook clips a line to 160 characters and the store clips it again on the
# way out, so nothing longer comes from a session. Matching a run of quote marks
# costs the square of its length, so a bound on the text is a bound on the time:
# a longer text is not a line, and offers nothing.
LONGEST = 400


def guess(text):
    """The commands in `text`, in the order they were written, each once."""
    if len(text) > LONGEST:
        return []
    # Whatever stands after a `$`, or between quotes, is the argument of
    # something: it claims every quote inside it, whether or not it can be
    # offered itself, so the inside of a command the lists do not know is never
    # offered as a command of its own.
    found, taken = [], []
    for m in DOLLAR_COMMAND.finditer(text):
        command = m.group(1).strip()
        taken.append((m.start(1), m.end()))
        # With words after it the end cannot be told from a comma or a full
        # stop that belongs to the command (`-F,`, `! -name`, `ls .`). A
        # backtick would run what it holds when pasted.
        if (reads_as_prompted(command) and COMPLETE.match(text, m.end())
                and not cut_or_broken(command) and "`" not in command
                and not joins_two_commands(command)
                and not ends_in_a_stray_mark(command)):
            found.append(Hit(m.start(1), m.end(), command))
    spans = sorted(((m, mark) for pattern, mark in QUOTES for m in pattern.finditer(text)),
                   key=lambda s: (s[0].start(), -s[0].end()))
    claimed = []
    for m, mark in spans:
        if any(start < m.end() and m.start() < end for start, end in taken):
            continue
        taken.append((m.start(), m.end()))
        claimed.append((m, mark))
    def claimed_at(position):
        return any(start <= position < end for start, end in taken)

    # With a quote left open anywhere, which pairs are real is not known.
    trusted = not any(not claimed_at(s.start()) for s in STRONG_STRAY.finditer(text))
    single_quotes = not any(not claimed_at(s.start()) for s in WEAK_STRAY.finditer(text))
    masked = list(text)
    for start, end in taken:
        masked[start:end] = "\0" * (end - start)
    masked = "".join(masked)
    for m, mark in claimed if trusted else ():
        said = m.group(1)
        if mark is None:
            # « make test » is how French sets it, with a space inside.
            said = said.strip()
        elif said != said.strip():
            # A quote that hugs a space inside (`"git commit -m "`) is the
            # closing quote of one phrase paired with the opening of the next.
            continue
        if (mark == "'" and not single_quotes) or AFTER_A_FLAG.search(text[:m.start()]):
            continue
        if argument_of_a_runner(masked[:m.start()]):
            continue
        # What stands after the prompt is stripped again: the space after the `$` may
        # be followed by any other whitespace, and a command that begins with it
        # is not the piece the person would paste.
        said = re.sub(r"^\$ +", "", said).strip()
        if quoted_command(said):
            found.append(Hit(m.start(), m.end(), said))
    ordered = []
    for hit in sorted(found):
        # Claude Code's `!` is never copied: the person adds it when the
        # command goes into a Claude prompt (the owner's rule, 2026-10-21).
        command = SHELL_PREFIX.sub("", hit.command)
        if command not in ordered:
            ordered.append(command)
    return ordered
