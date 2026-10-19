"""What a project is about, in one line, for the top of its column.

The first of these that exists, in this order: the person's own line; a
track's goal; a repository's README or agent instructions; and otherwise a
guess made of the latest session titles, marked as one so it invites a line
rather than passing for a fact.

Nothing here asks the brain. A card's "notes" link does that, on a click, and
the brain is never where a context line comes from.

Every text in here is whatever a file or a session said, kept as it was said:
the page prints it as text and never as markup, so nothing is stripped for
safety here.
"""
LIMIT = 140          # about: the line is cut between words, full text on hover
GUESS_TITLES = 2
GUESS_JOIN = " · "
ELLIPSIS = "…"
TRIM = " ,;:.-–—"


def squash(text):
    """One line: runs of whitespace, newlines included, become one space."""
    return " ".join(str(text).split())


def cut(text, limit=LIMIT):
    """The text as it is, or cut between words to fit with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    space = head.rfind(" ")
    if space >= limit // 2:
        head = head[:space]
    return head.rstrip(TRIM) + ELLIPSIS


def made(source, text, full=None):
    """The roster's context line: where it came from, what the card shows,
    what the hover shows."""
    full = squash(text) if full is None else full
    return {"source": source, "line": cut(squash(text)), "full": full,
            "guess": source == "guess"}


def guess(rows):
    """The latest session titles of the project, two at most, each once."""
    titles = []
    for m in sorted(rows, key=lambda m: -m["updatedAt"]):
        title = squash(m.get("title") or "")
        if title and title not in titles:
            titles.append(title)
        if len(titles) == GUESS_TITLES:
            break
    return GUESS_JOIN.join(titles)


def context_line(project, rows, own_lines):
    """A project's context line, or None for the column of sessions that have
    no project (which has nothing to be about)."""
    if project["kind"] == "none":
        return None
    own = own_lines.get(project["id"])
    if isinstance(own, str) and squash(own):
        return made("own", own)
    return made("guess", guess(rows))
