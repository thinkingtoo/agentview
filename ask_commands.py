"""Which words in a session's line are a command for the person to run.

The session-line hook writes `ask` as free text, so this is a guess, and it
errs towards offering too little: a missing button costs a selection with the
mouse, a button on a sentence costs the person's trust in every other button.
"""
import re

# Every way a session quotes something. A straight or curly single quote is
# also an apostrophe: one only opens a quote at the start of a word and closes
# it at the end of one, so "don't" and "the owner's call" never pair up.
QUOTES = [re.compile(p) for p in (
    r'"([^"\n]+)"', r"`([^`\n]+)`", r"\u201c([^\u201d\n]+)\u201d", r"\u00ab([^\u00bb\n]+)\u00bb",
    r"(?<!\w)'([^'\n]+)'(?!\w)", r"(?<!\w)\u2018([^\u2019\n]+)\u2019(?!\w)")]

# `$ ` as a shell prompt: after a space or a colon, then a command word. `$5`
# and `$HOME` have no space after the sign and `$ 5` no command word.
PROMPTED = re.compile(
    r"(?:^|[\s:])\$ +([A-Za-z./~][^\n]*?)"
    # Where the command ends and the sentence goes on.
    r"(?=\s\$ |,\s|\.(?:\s|$)|[?!](?:\s|$)|\s[—–]\s|\s\(|$)")

# What a quoted phrase has to start with to be taken for a command. Prose in
# quotes ("release notes") has no such word; a program the list does not know
# gets no button, and that is the accepted miss.
PATHS = ("./", "../", "~/")
SCRIPT = re.compile(r"\.(sh|bash|py|js|mjs|rb|pl)$")
PROGRAMS = frozenset("""
git gh npm npx pnpm yarn node python python3 pip pip3 uv cargo docker kubectl
systemctl journalctl ssh scp rsync curl wget cd ls cp mv rm mkdir touch chmod
chown ln grep rg sed awk tar sudo bash sh echo tmux pytest ruff diff jq ps df du
""".split())
# Programs that are also words of a sentence ("go ahead", "make sure", "find
# out", "claude code"): they count when a word after them is no plain word
# (a flag, a path, a dot) or, for the two build tools, names a target.
WORDS = frozenset("make go find head tail cat source export kill pkill claude codex".split())
TARGETS = frozenset("test build install run clean lint check fmt vet all deploy tidy".split())


def reads_as_command(text):
    """A known program, or a script run by its path, with something after it.

    One word alone is a name ("git", "./notes", "go"), not an instruction;
    the exception is a script named by its path ("./deploy.sh").
    """
    words = text.split()
    if not words:
        return False
    if len(words) == 1:
        return words[0].startswith(PATHS) and bool(SCRIPT.search(words[0]))
    first, rest = words[0], words[1:]
    if first in PROGRAMS or first.startswith(PATHS):
        return True
    if first in WORDS:
        return (any(re.search(r"[^A-Za-z]", w) for w in rest)
                or (first in ("make", "go") and rest[0] in TARGETS))
    return False


def reads_as_prompted(text):
    """What follows a `$ `: the sign says it is a command, so one word is
    enough, but it must still be a program and not a word of the sentence
    ("in $ or euros"). A program of the project's own has a hyphen, an
    underscore, a dot or a slash in its name."""
    words = text.split()
    return bool(words) and (words[0] in PROGRAMS or words[0] in WORDS or words[0].startswith(PATHS)
                            or any(c in words[0] for c in "-_./"))


def guess(text):
    """The commands in `text`, in the order they were written, each once."""
    # A command after `$` runs to the end of its sentence and claims any quote
    # inside it. A quoted phrase that is a command claims what is inside it.
    found = [(m.start(1), m.end(), m.group(1).strip()) for m in PROMPTED.finditer(text)
             # The line is cut with an ellipsis, and half a command pasted
             # into a terminal is worse than none.
             if not m.group(1).endswith("\u2026") and reads_as_prompted(m.group(1))]
    quoted = sorted((m for q in QUOTES for m in q.finditer(text)),
                    key=lambda m: (m.start(), -m.end()))
    for m in quoted:
        if any(a < m.end() and m.start() < b for a, b, _ in found):
            continue
        said = re.sub(r"^\$ +", "", m.group(1).strip())
        if reads_as_command(said):
            found.append((m.start(), m.end(), said))
    return [command for _, _, command in sorted(found)]
