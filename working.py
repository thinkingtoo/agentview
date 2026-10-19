"""The working-on line: what job a session is on, in one line.

The first of these that says something new: the person's own line; the `did`
the session wrote (the last one, until it writes another); Claude Code's
title. With none of those, a stand-in the page greys: the last prompt, then
the branch, then the folder. A line that only repeats the project's name, its
context line or the session's own name says nothing new, and the next source
speaks instead; with nothing left the tile has no line.

The roster says where the line came from. The text is whatever the session or
the person wrote, kept as it was said: the page sets it as text and never as
markup, so nothing is stripped for safety here.
"""
import os
import re

import context

OWN, DID, TITLE, PROMPT, PLACE = "own", "did", "title", "prompt", "place"
SOURCES = (OWN, DID, TITLE, PROMPT, PLACE)

# The prompt is a stand-in, clipped like a context line. The rest is a line by
# nature; the bound only keeps one poll from carrying an essay, and the hover
# shows what the tile cuts.
PROMPT_LIMIT = context.LINE_LIMIT
LINE_LIMIT = 300

SLUG_MARKS = re.compile(r"[\s_-]+")


def same(text):
    """Two lines are the same line when they differ only in case, in spacing
    and in the marks of a slug: `my-shop` repeats `My shop`."""
    return " ".join(SLUG_MARKS.split(str(text).casefold())).strip()


def folder_of(cwd):
    return os.path.basename(cwd.rstrip("/")) if isinstance(cwd, str) else ""


def _candidates(m):
    """What the session offers, in the order it is preferred, as
    `(source, text)`."""
    yield OWN, m["title"] if m.get("overridden") else ""
    yield DID, m.get("did")
    yield TITLE, "" if m.get("overridden") else m.get("title")
    yield PROMPT, m.get("prompt")
    yield PLACE, m.get("branch")
    yield PLACE, folder_of(m.get("cwd"))


def line_of(m, project_name, about):
    """`(text, source)` for a session's tile, or `("", "")`.

    `project_name` is what the column is called (None for the column of no
    project, which has no name to repeat) and `about` its context line as the
    roster builds it, or None.
    """
    seen = set()
    for said in (project_name, m.get("name")):
        if isinstance(said, str):
            seen.add(same(said))
    if about:
        seen.update((same(about["line"]), same(about["full"])))
    seen.discard("")
    for source, text in _candidates(m):
        if not isinstance(text, str):
            continue
        text = context.squash(text)
        if not text or same(text) in seen:
            continue
        limit = PROMPT_LIMIT if source == PROMPT else LINE_LIMIT
        return context.cut(text, limit), source
    return "", ""
