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
# A straight mark that is no part of a pair (or an apostrophe inside a word)
# means the session's pairing cannot be trusted: which marks open and which
# close is not for a guess to settle, so nothing of that kind is offered.
STRAY = {
    '"': re.compile(r'(?<!\\)"'),
    "`": re.compile(r"(?<!\\)`"),
    "'": re.compile(r"(?<!\w)'|'(?!\w)"),
}
ESCAPED_QUOTE = re.compile(r"\\[\"`]")
# A quote that comes right after a flag is the argument of that flag (`sh -c
# "rm -rf x"`, `--command "sudo reboot"`), not a command of its own.
AFTER_A_FLAG = re.compile(r"(?:^|\s)--?[\w-]+\s+$")
NESTED_OPENER = re.compile(r"[\u201c\u00ab\u2018]")

# `$ ` as a shell prompt: after a space, a colon or an opening bracket, then a
# command word. `$5`
# and `$HOME` have no space after the sign, `$ 5` no command word, and `20 $`
# is an amount. A quoted argument is one unit, so the comma in `-m "one, two"`
# does not end the command; the end of the line does, so the match can never
# fail and the engine never has to try the quoted and the plain way of reading
# each quote.
DOLLAR_COMMAND = re.compile(
    r"(?<!\d)(?:^|[\s:(\[{])\$ +([A-Za-z./~]"
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
    # `ends_in_a_stray_dot`). A `?` after a space is French typography; a `!`
    # after a space is that too at the end or before a capital letter, and
    # otherwise the shell's negation (`find ! -name x`).
    r"(?=\s\$ |,\s|(?<=[\w\"'`)\]}>])\.(?:\s|$)|\.+\s+(?=[A-Z])"
    r"|(?<!\s)[?!](?:\s|$)|\s\?(?:\s|$)|\s!(?:\s*$|\s+(?=[A-Z]))"
    r"|\s[\u2014\u2013]\s|\s\(|[\u00bb\u201d]|\n|$)")
# What may follow a command for it to be the whole of its line: the full stop,
# question mark or exclamation mark that ends the sentence. Another prompt does
# not count: what stands between two prompts could be an argument of the first.
COMPLETE = re.compile(r"\s*[.?!]*\s*$")

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


class Hit(NamedTuple):
    start: int
    end: int
    command: str


def reads_as_command(text):
    """A known program, or a script run by its path, with something after it.

    One word alone is a name ("git", "./notes", "go"), not an instruction;
    the exception is a script named by its path ("./deploy.sh"). A path with
    plain words after it ("~/Google Drive/My Drive") is a name that has spaces
    in it, so a path starts a command only when it names a script or a flag
    follows.
    """
    words = text.split()
    if not words:
        return False
    first, rest = words[0], words[1:]
    pathlike = first.startswith(PATHS) or (first.startswith("/") and first.count("/") > 1)
    if not rest:
        return pathlike and bool(SCRIPT.search(first))
    if pathlike:
        return bool(SCRIPT.search(first)) or any(FLAG.match(w) for w in rest)
    if ENV_ASSIGNMENT.match(first):
        return True
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
    """What follows a `$ `: the sign says it is a command, so one word is
    enough, but it must still be a program and not a word of the sentence
    ("in $ or euros")."""
    words = text.split()
    if not words:
        return False
    first = words[0]
    return (first in KNOWN or first.startswith(PATHS)
            or (first.startswith("/") and first.count("/") > 1 and re.search(r"[A-Za-z]", first) is not None)
            or ENV_ASSIGNMENT.match(first) is not None or OWN_PROGRAM.fullmatch(first) is not None)


QUOTED_RUN = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\\n])*`|(?<!\w)'[^'\n]*'(?!\w)")
QUOTE_OPENER = re.compile(r"[\"`]|(?<!\w)'")
CLOSERS = (("(", ")"), ("[", "]"), ("{", "}"))


def cut_or_broken(command):
    """Half a command pasted into a terminal is worse than none: the line was
    cut with an ellipsis, a quote opened in it was never closed, or it holds a
    bracket that closes something outside it ("(run $ make test)"). An
    apostrophe inside a word ("it's") does not open a quote."""
    return (command.endswith("\u2026")
            or QUOTE_OPENER.search(QUOTED_RUN.sub(" ", command)) is not None
            or any(command.count(close) > command.count(open_) for open_, close in CLOSERS))


def ends_in_a_stray_dot(command):
    """A command that ends in a `.` the session may have meant as the end of
    its sentence: `rm -rf ~/.cache/maple/*.`, `cd ~.`, `go test ./....`,
    `pip install -e ..`. The dot is the command's own only as a word by itself
    (`pip install -e .`) or as Go's `/...`."""
    last = command.split()[-1]
    return command.endswith(".") and last != "." and not last.endswith("/...")


def quoted_command(said):
    """The text between a pair of quotes, as a command: one a shell could take
    whole. A backtick would run what it holds, an escaped or a nested quote
    means the pairing is not the session's, and a comma or a colon at the end
    is the typography of the quote."""
    return (reads_as_command(said) and not cut_or_broken(said)
            and not ESCAPED_QUOTE.search(said) and "`" not in said
            and not NESTED_OPENER.search(said) and not said.endswith((",", ";", ":")))


def guess(text):
    """The commands in `text`, in the order they were written, each once."""
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
                and not ends_in_a_stray_dot(command)):
            found.append(Hit(m.start(1), m.end(), command))
    spans = sorted(((m, mark) for pattern, mark in QUOTES for m in pattern.finditer(text)),
                   key=lambda s: (s[0].start(), -s[0].end()))
    claimed = []
    for m, mark in spans:
        if any(start < m.end() and m.start() < end for start, end in taken):
            continue
        taken.append((m.start(), m.end()))
        claimed.append((m, mark))
    # A mark outside every claimed region has no partner the session meant.
    untrusted = {mark for mark, stray in STRAY.items()
                 if any(not any(start <= s.start() < end for start, end in taken)
                        for s in stray.finditer(text))}
    for m, mark in claimed:
        said = m.group(1)
        # A quote that hugs a space inside (`"git commit -m "`) is the closing
        # quote of one phrase paired with the opening of the next.
        if mark in untrusted or said != said.strip() or AFTER_A_FLAG.search(text[:m.start()]):
            continue
        said = re.sub(r"^\$ +", "", said)
        if quoted_command(said):
            found.append(Hit(m.start(), m.end(), said))
    ordered = []
    for hit in sorted(found):
        if hit.command not in ordered:
            ordered.append(hit.command)
    return ordered
