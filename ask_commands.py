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

# Every way a session quotes something. A straight or curly single quote is
# also an apostrophe: one only opens a quote at the start of a word and closes
# it at the end of one, so "don't" and "the owner's call" never pair up. A
# backslash keeps the quote it escapes inside the quote.
QUOTES = [re.compile(p) for p in (
    r'"((?:\\.|[^"\\\n])+)"', r"`((?:\\.|[^`\\\n])+)`", r"“([^”\n]+)”", r"«([^»\n]+)»",
    r"(?<!\w)'([^'\n]+)'(?!\w)", r"(?<!\w)‘([^’\n]+)’(?!\w)")]
ESCAPED_QUOTE = re.compile(r"\\[\"`]")

# `$ ` as a shell prompt: after a space or a colon, then a command word. `$5`
# and `$HOME` have no space after the sign, `$ 5` no command word, and `20 $`
# is an amount. A quoted argument is one unit, so the comma in `-m "one, two"`
# does not end the command; the end of the line does, so the match can never
# fail and the engine never has to try the quoted and the plain way of reading
# each quote.
DOLLAR_COMMAND = re.compile(
    r"(?<!\d)(?:^|[\s:])\$ +([A-Za-z./~]"
    r"(?:\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\\n])*`|(?<!\w)'[^'\n]*'(?!\w)"
    # A flag with a comma stuck to it (`-F,`) is one unit, not the end of a clause.
    r"|(?<=\s)--?\w[\w-]*,|[^\n])*?)"
    # Where the sentence goes on. Not every one of these ends a command (a
    # `ls .` or a quoted `, ` can look like one), which is why a command with
    # words after it is not offered at all: see COMPLETE. A period counts after
    # a word or a closing quote or bracket, or before a capital letter, but not
    # as part of `find .`, `cd ..` or `go test ./...`. A `?` after a space is
    # French typography; a `!` after a space is that too at the end or before
    # a capital letter, and otherwise the shell's negation (`find ! -name x`).
    r"(?=\s\$ |,\s|(?<=[\w\"'`)\]])\.(?:\s|$)|(?<![.\s])\.\s+(?=[A-Z])"
    r"|(?<!\s)[?!](?:\s|$)|\s\?(?:\s|$)|\s!(?:\s*$|\s+(?=[A-Z]))"
    r"|\s[\u2014\u2013]\s|\s\(|[\u00bb\u201d]|\n|$)")
# What may follow a command for it to be the whole of its line: the full stop,
# question mark or exclamation mark that ends the sentence, or the next prompt.
COMPLETE = re.compile(r"\s*[.?!]*\s*$|\s\$ ")

PATHS = ("./", "../", "~/")
SCRIPT = re.compile(r"\.(sh|bash|py|js|mjs|rb|pl)$")
ENV_ASSIGNMENT = re.compile(r"[A-Z_][A-Z0-9_]*=\S*$")
# What no plain sentence has in a word: a flag, a path, a dot between letters,
# a bare number, a string, an @, an =, a shell sign. An apostrophe, a comma, a
# hyphen inside a word, an accent or a digit inside a name ("v2") are prose.
ARGUMENT_SIGN = re.compile(r"""^-+\w|^\.|^~|^\d+$|[/@=*\\|&;<>$"`]|\w\.\w""")

# What a quoted phrase has to start with to be taken for a command, in three
# tiers by how likely the same words are plain prose. A program the lists do
# not know gets no button in quotes, and that is the accepted miss.
#
# Names nobody says in a sentence: anything after them is an argument.
ANY_ARGUMENT = frozenset("""
ls cp mv rm mkdir chmod chown ln grep rg sed awk jq pytest ruff psql sqlite3 crontab openssl
ssh-add ssh-keygen apt-get dpkg ufw certbot
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
# Words of a sentence that are also programs ("find out", "touch base", "echo
# chamber", "claude code", "ssh keys"): they count only when a word after them
# carries one of the signs above.
PROSE_PROGRAMS = frozenset("""
find head tail cat source export kill pkill claude codex python python3 node npx ssh scp rsync
curl wget touch echo tmux journalctl ps df du cd diff tar bash sh
""".split())

KNOWN = ANY_ARGUMENT | SUBCOMMANDS.keys() | PROSE_PROGRAMS | WRAPPERS


class Hit(NamedTuple):
    start: int
    end: int
    command: str


def reads_as_command(text):
    """A known program, or a script run by its path, with something after it.

    One word alone is a name ("git", "./notes", "go"), not an instruction;
    the exception is a script named by its path ("./deploy.sh").
    """
    words = text.split()
    if not words:
        return False
    first, rest = words[0], words[1:]
    if not rest:
        return (first.startswith(PATHS) or (first.startswith("/") and first.count("/") > 1)) \
            and bool(SCRIPT.search(first))
    if first.startswith(PATHS) or (first.startswith("/") and first.count("/") > 1):
        return True
    if ENV_ASSIGNMENT.match(first):
        return True
    if first in WRAPPERS:
        return reads_as_command(" ".join(rest))
    if first in ANY_ARGUMENT:
        return True
    if first in KNOWN and any(ARGUMENT_SIGN.search(w) for w in rest):
        return True
    return (first in SUBCOMMANDS and rest[0] in SUBCOMMANDS[first]
            and (len(rest) == 1 or first not in ONE_WORD_AFTER))


def reads_as_prompted(text):
    """What follows a `$ `: the sign says it is a command, so one word is
    enough, but it must still be a program and not a word of the sentence
    ("in $ or euros"). A program of the project's own has a hyphen, an
    underscore, a dot or a slash in its name."""
    words = text.split()
    # "/ mois" and "." are no program: a name has a letter in it.
    if not words or not re.search(r"[A-Za-z]", words[0]):
        return False
    return (words[0] in KNOWN or words[0].startswith(PATHS)
            or ENV_ASSIGNMENT.match(words[0]) is not None
            or any(c in words[0] for c in "-_./"))


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
        # stop that belongs to the command (`-F,`, `! -name`, `ls .`).
        # A backtick would run what is between the ticks when pasted.
        if (reads_as_prompted(command) and COMPLETE.match(text, m.end())
                and not cut_or_broken(command) and "`" not in command):
            found.append(Hit(m.start(1), m.end(), command))
    quoted = sorted((m for q in QUOTES for m in q.finditer(text)),
                    key=lambda m: (m.start(), -m.end()))
    for m in quoted:
        if any(start < m.end() and m.start() < end for start, end in taken):
            continue
        taken.append((m.start(), m.end()))
        said = re.sub(r"^\$ +", "", m.group(1).strip())
        # Which quote an escaped one belongs to is not for a guess to settle,
        # and a quote that hugs a space inside (`"git commit -m "`) is the
        # closing quote of one phrase paired with the opening of the next.
        if (reads_as_command(said) and not ESCAPED_QUOTE.search(said)
                and m.group(1) == m.group(1).strip()):
            found.append(Hit(m.start(), m.end(), said))
    ordered = []
    for hit in sorted(found):
        if hit.command not in ordered:
            ordered.append(hit.command)
    return ordered
