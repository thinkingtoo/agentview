"""Which words in a session's line are a command for the person to run.

The session-line hook writes `ask` as free text, so this is a guess, and it
errs towards offering too little: a missing button costs a selection with the
mouse, a button on a sentence costs the person's trust in every other button.
"""
import re
from typing import NamedTuple

# Every way a session quotes something. A straight or curly single quote is
# also an apostrophe: one only opens a quote at the start of a word and closes
# it at the end of one, so "don't" and "the owner's call" never pair up.
QUOTES = [re.compile(p) for p in (
    r'"([^"\n]+)"', r"`([^`\n]+)`", r"“([^”\n]+)”", r"«([^»\n]+)»",
    r"(?<!\w)'([^'\n]+)'(?!\w)", r"(?<!\w)‘([^’\n]+)’(?!\w)")]

# `$ ` as a shell prompt: after a space or a colon, then a command word. `$5`
# and `$HOME` have no space after the sign and `$ 5` no command word. A quoted
# argument is one unit, so the comma in `-m "one, two"` does not end the
# command; the end of the line does, so the match can never fail and the
# engine never has to try the quoted and the plain way of reading each quote.
DOLLAR_COMMAND = re.compile(
    r"(?:^|[\s:])\$ +([A-Za-z./~](?:\"[^\"\n]*\"|`[^`\n]*`|(?<!\w)'[^'\n]*'(?!\w)|[^\n])*?)"
    # Where the command ends and the sentence goes on.
    r"(?=\s\$ |,\s|\.(?:\s|$)|[?!](?:\s|$)|\s[—–]\s|\s\(|\n|$)")

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
cd ls cp mv rm mkdir chmod chown ln sudo bash sh grep rg sed awk tar diff jq pytest ruff
brew apt apt-get dpkg crontab psql sqlite3 ollama openssl ssh-add ssh-keygen tailscale ufw certbot
""".split())
# Tools with a fixed set of subcommands. "git status" is a command and "git
# history" is a title, so a plain word after them has to be one of theirs.
BUILD_TARGETS = "test build install run clean lint check fmt vet all deploy tidy dev generate".split()
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
    "make": " ".join(BUILD_TARGETS),
    "go": " ".join(BUILD_TARGETS) + " mod get",
}.items()}
# Words of a sentence that are also programs ("find out", "touch base", "echo
# chamber", "claude code", "ssh keys"): they count only when a word after them
# carries one of the signs above.
PROSE_PROGRAMS = frozenset("""
find head tail cat source export kill pkill claude codex python python3 node npx ssh scp rsync
curl wget touch echo tmux journalctl ps df du
""".split())

KNOWN = ANY_ARGUMENT | SUBCOMMANDS.keys() | PROSE_PROGRAMS


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
    if first in ANY_ARGUMENT:
        return True
    if first in KNOWN and any(ARGUMENT_SIGN.search(w) for w in rest):
        return True
    return first in SUBCOMMANDS and rest[0] in SUBCOMMANDS[first]


def reads_as_prompted(text):
    """What follows a `$ `: the sign says it is a command, so one word is
    enough, but it must still be a program and not a word of the sentence
    ("in $ or euros"). A program of the project's own has a hyphen, an
    underscore, a dot or a slash in its name."""
    words = text.split()
    return bool(words) and (words[0] in KNOWN or words[0].startswith(PATHS)
                            or ENV_ASSIGNMENT.match(words[0]) is not None
                            or any(c in words[0] for c in "-_./"))


def cut_or_broken(command):
    """Half a command pasted into a terminal is worse than none: the line was
    cut with an ellipsis, or a quote opened in it was never closed."""
    return command.endswith("\u2026") or command.count('"') % 2 or command.count("`") % 2


def guess(text):
    """The commands in `text`, in the order they were written, each once."""
    # A command after `$` runs to the end of its sentence and claims any quote
    # inside it, whether or not it can be offered. A quoted phrase that is a
    # command claims what is inside it.
    found, taken = [], []
    for m in DOLLAR_COMMAND.finditer(text):
        command = m.group(1).strip()
        if reads_as_prompted(command):
            taken.append((m.start(1), m.end()))
            if not cut_or_broken(command):
                found.append(Hit(m.start(1), m.end(), command))
    quoted = sorted((m for q in QUOTES for m in q.finditer(text)),
                    key=lambda m: (m.start(), -m.end()))
    for m in quoted:
        if any(start < m.end() and m.start() < end for start, end in taken):
            continue
        said = re.sub(r"^\$ +", "", m.group(1).strip())
        if reads_as_command(said):
            taken.append((m.start(), m.end()))
            found.append(Hit(m.start(), m.end(), said))
    ordered = []
    for hit in sorted(found):
        if hit.command not in ordered:
            ordered.append(hit.command)
    return ordered
