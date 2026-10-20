"""The working-on line: what job a session is on, in one line.

The first of these that says something new: the person's own line; the `did`
the session wrote (the last one, until it writes another); Claude Code's
title. With none of those, a stand-in the page greys: the last prompt, then
the branch, then the folder. A line that only repeats the project's name, its
context line or the session's own name says nothing new, and the next source
speaks instead; with nothing left the tile has no line.

The roster says where the line came from. The text is whatever the session or
the person wrote, kept as it was said: the page sets it as text and never as
markup, so nothing is stripped for safety here. It is one line, whole up to a
bound: the page clips it to the tile and shows all of it on hover.
"""
import os
import re

import context

OWN, DID, TITLE, PROMPT, PLACE = "own", "did", "title", "prompt", "place"

SLUG_MARKS = re.compile(r"[\s_-]+")

# A line is carried this long. Only the start of a text is looked at: a
# pasted file as the last prompt is a hundred kilobytes, and the roster is
# made every few seconds for every session on the machine.
CARRIED = context.PARAGRAPH_MAX
LOOKED_AT = 8 * CARRIED


def repeat_key(text):
    """What a line is compared by to tell a repeat.

    Case, spacing and the marks of a slug are left out, so `my-shop` repeats
    the project `My shop`.
    """
    return " ".join(SLUG_MARKS.split(str(text).casefold())).strip()


def repeats(project_name, about):
    """What a column already says, for its tiles to leave out.

    Its name (None for the column of no project, which has no name to repeat)
    and its context line as the roster builds it (or None), cut and whole.
    """
    said = {repeat_key(project_name)} if isinstance(project_name, str) else set()
    if about:
        said.update((repeat_key(about["line"]), repeat_key(about["full"])))
    said.discard("")
    return frozenset(said)


def _folder(cwd):
    return os.path.basename(cwd.rstrip("/")) if isinstance(cwd, str) else ""


def _candidates(m):
    """What the session offers, in the order it is preferred, as `(source, text)`.

    The title is Claude Code's own: your line, which the older page reads in
    its place, is `own`.
    """
    yield OWN, m.get("own")
    yield DID, m.get("did")
    yield TITLE, m.get("generated", m.get("title"))
    yield PROMPT, m.get("prompt")
    yield PLACE, m.get("branch")
    yield PLACE, _folder(m.get("cwd"))


def line_of(m, column_says=frozenset()):
    """`(text, source)` for a session's tile, or `("", "")`.

    `column_says` is what its column already says (`repeats`).
    """
    name = repeat_key(m["name"]) if isinstance(m.get("name"), str) else ""
    if name:
        column_says = column_says | {name}
    for source, text in _candidates(m):
        if not isinstance(text, str):
            continue
        text = context.cut(context.squash(text[:LOOKED_AT]), CARRIED)
        if text and repeat_key(text) not in column_says:
            return text, source
    return "", ""
