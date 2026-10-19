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
import re

import projects

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


# ------------------------------------------------------------ reading markdown

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
STATUS = re.compile(r"^\s*[_*]*status:[_*\s]*([a-z]+)", re.IGNORECASE)
STATUS_WORDS = ("OPEN", "PAUSED", "MET")
# The end of a sentence: a full stop, a question or exclamation mark (and any
# closing quote) before a capital letter or a digit. "e.g. the" and
# "server.py" do not end one.
SENTENCE_END = re.compile(r"""[.!?]["'\u201d\u2019)\]]*(?=\s+[A-Z0-9"\u201c\u2018(\[]|\s*$)""")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
BOLD = re.compile(r"(\*\*|__)(.+?)\1")
READ = 200_000       # a goal or a README is read this far, no further


def read(path):
    """The start of a text file, or "" when it cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(READ)
    except OSError:
        return ""


def unfenced(text):
    """The lines of a markdown text that are not inside a code fence. A fence
    reads as a blank line, so it ends the paragraph before it."""
    fence = None
    for line in text.splitlines():
        marker = FENCE.match(line)
        if marker:
            fence = marker.group(1) if fence is None else (None if marker.group(1) == fence else fence)
            yield ""
        elif fence is None:
            yield line


def section(lines, title):
    """The lines under the first heading called `title`, up to the next
    heading of the same or a higher level."""
    out, level = [], None
    for line in lines:
        heading = HEADING.match(line)
        if heading:
            if level is not None and len(heading.group(1)) <= level:
                break
            if level is None and heading.group(2).strip(" :*_`").casefold() == title:
                level = len(heading.group(1))
                continue
        if level is not None:
            out.append(line)
    return out


def paragraphs(lines):
    """Runs of lines between blank ones. A heading is a paragraph of its own."""
    run = []
    for line in lines:
        if not line.strip() or HEADING.match(line):
            if run:
                yield run
            run = []
            if line.strip():
                yield [line]
        else:
            run.append(line)
    if run:
        yield run


def plain(text):
    """Markdown as the plain text it says: a link is its label, an image is
    nothing, bold and code lose their marks. Anything else, tags included, is
    left as it was written."""
    text = LINK.sub(r"\1", IMAGE.sub("", text))
    return squash(BOLD.sub(r"\2", text).replace("`", ""))


def first_sentence(text):
    end = SENTENCE_END.search(text)
    return text[:end.end()] if end else text


# ------------------------------------------------------------------ the track

def goal_file(track):
    """The text of `<pm>/<track>.goal.md`, or "". Only a name a track can
    have is looked up: the identity comes from the page."""
    if not projects.TRACK_NAME.match(track):
        return ""
    return read(projects.pm_dir() / f"{track}.goal.md")


def track_card(track):
    """What a track's goal file gives the card: (the Outcome paragraph, or "";
    `{"status", "progress"}`)."""
    lines = list(unfenced(goal_file(track)))
    status = next((m.group(1).upper() for m in map(STATUS.match, lines) if m), "")
    status = status if status in STATUS_WORDS else ""
    boxes = [b.group(1) for b in map(BOX.match, section(lines, "done when")) if b]
    total, done = len(boxes), sum(1 for b in boxes if b != " ")
    if status == "MET":
        progress = {"done": total, "total": total, "text": "done", "met": True}
    elif total:
        progress = {"done": done, "total": total, "text": f"{done} of {total}", "met": False}
    else:
        progress = None
    outcome = next((plain(" ".join(p)) for p in paragraphs(section(lines, "outcome"))
                    if not HEADING.match(p[0])), "")
    return outcome, {"status": status, "progress": progress}


# ----------------------------------------------------------------- the line

def card(project, rows, own_lines):
    """A project's context line and, for a track, its status and progress:
    `(line, track)`. The column of sessions with no project has neither."""
    if project["kind"] == "none":
        return None, None
    outcome, track = "", None
    if project["kind"] == "track":
        outcome, track = track_card(project["raw"])
    own = own_lines.get(project["id"])
    if isinstance(own, str) and squash(own):
        return made("own", own), track
    if outcome:
        return made("goal", first_sentence(outcome), outcome), track
    return made("guess", guess(rows)), track
