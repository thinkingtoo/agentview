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
import os
import re

import projects

LINE_LIMIT = 140     # about: the line is cut between words, full text on hover
PARAGRAPH_MAX = 1500  # no text is carried longer: the hover is a hover, and every poll carries it
GUESS_TITLES = 2
GUESS_JOIN = " · "
ELLIPSIS = "…"
TRIM = " ,;:.-–—"


def squash(text):
    """One line: runs of whitespace, newlines included, become one space."""
    return " ".join(str(text).split())


def cut(text, limit=LINE_LIMIT):
    """The text as it is, or cut between words to fit with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    space = head.rfind(" ")
    if space >= limit // 2:
        head = head[:space]
    return head.rstrip(TRIM) + ELLIPSIS


def line_from(source, text, full=None):
    """The roster's context line: where it came from, what the card shows,
    what the hover shows."""
    text = squash(text)[:PARAGRAPH_MAX]
    full = text if full is None else full[:PARAGRAPH_MAX]
    return {"source": source, "line": cut(text), "full": full, "guess": source == "guess"}


def notes_query(name, line):
    """What the notes link asks: the project's name and its context line,
    without the ellipsis of a cut one."""
    return f"{name} {line['line'].removesuffix(ELLIPSIS)}".strip()


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
# The rest of a heading line is taken whole and its closing marks are cut in
# Python: a pattern that tries to find them itself backtracks cubically on a
# line of many spaces, and this runs on every poll.
HEADING = re.compile(r"^\s{0,3}(#{1,6})(?:\s+(.*))?$")
CLOSING_MARKS = re.compile(r"(?:^|\s)#+\s*$")
# `**Outcome:** text` or `**Outcome**: text`: some goal files label a section
# in bold, on a line of its own or with its text after it, not with a heading.
LABEL = re.compile(r"^\s{0,3}\*\*([^*:\n]+?)(?::\*\*|\*\*\s*:)\s*(.*)$")
BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
STATUS = re.compile(r"^\s*[_*]*status:[_*\s]*([a-z]+)", re.IGNORECASE)
STATUS_WORDS = ("OPEN", "PAUSED", "MET")
# The end of a sentence: a full stop, a question or exclamation mark (and any
# closing quote) before a capital letter, in any alphabet, or a digit or an
# opening quote. "e.g. the" and "server.py" do not end one.
SENTENCE_END = re.compile(r"""[.!?]["'\u201d\u2019)\]]*(?=\s+(\S)|\s*$)""")
OPENERS = "\"'\u201c\u2018(["
# A link or an image points with an address in brackets, one level of round
# brackets allowed inside it (`Rule_(math)`, `3.10%20(min)`), or with a
# reference, `[text][ref]`.
POINTS_TO = r"(?:\((?:[^()]|\([^()]*\))*\)|\[[^\]]*\])"
LINK = re.compile(r"\[([^\]]*)\]" + POINTS_TO)
IMAGE = re.compile(r"!\[[^\]]*\]" + POINTS_TO)
BOLD = re.compile(r"(\*\*|__)(.+?)\1")
CODE = re.compile(r"`([^`]+)`")
# Tags that only format a word: they go, their text stays. Any other tag
# is left as it was written, and the page prints it as text.
FORMATTING = re.compile(r"</?(a|abbr|b|big|br|cite|code|del|em|font|i|ins|kbd|mark|s|small|span|strike|strong"
                        r"|sub|sup|u)\b[^<>]*>", re.IGNORECASE)
HTML_LINK = re.compile(r"<a\b[^<>]*>[^<]*</a>", re.IGNORECASE)
READ = 100_000       # a goal or a README is read this far, no further


def read(path):
    """The start of a text file, or "" when it cannot be read."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
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


def heading_text(heading):
    """The words of a heading line, without its closing marks."""
    return CLOSING_MARKS.sub("", heading.group(2) or "").strip()


def section(lines, title):
    """The lines under the first heading, or bold label, called `title`. A
    heading's section runs to the next heading of the same or a higher level; a
    label's, to the next heading or label, and what follows the label on its
    own line is the section's first line."""
    out, level = [], None                       # level 0: opened by a label
    for line in lines:
        heading = HEADING.match(line)
        label = None if heading else LABEL.match(line)
        depth = len(heading.group(1)) if heading else 0
        if level is not None and ((heading and (level == 0 or depth <= level)) or (label and level == 0)):
            break
        if level is None and heading and heading_text(heading).strip(" :*_`").casefold() == title:
            level = depth
            continue
        if level is None and label and label.group(1).strip(" _`").casefold() == title:
            level = 0
            if label.group(2):
                out.append(label.group(2))
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
    nothing, bold and code lose their marks, and so do the tags that only
    format. What stands inside a code span is code and stays exactly as it
    was written. Anything else, other tags included, is left as it was."""
    spans = []

    def keep(code):
        spans.append(code.group(1))
        return f"\0{len(spans) - 1}\0"

    text = CODE.sub(keep, text.replace("\0", ""))      # the NULs are ours from here on
    text = LINK.sub(r"\1", IMAGE.sub("", text))
    text = FORMATTING.sub(lambda tag: " " if tag.group(1).lower() == "br" else "", text)
    text = BOLD.sub(r"\2", text)
    return squash(re.sub(r"\0(\d+)\0", lambda at: spans[int(at.group(1))], text).replace("`", ""))


def first_sentence(text):
    for end in SENTENCE_END.finditer(text):
        after = end.group(1)
        if after is None or after.isupper() or after.isdigit() or after in OPENERS:
            return text[:end.end()]
    return text


def bare_tag(text):
    """A text that is one tag and nothing else, like the `<REPLACE: one
    sentence.>` a goal template holds until someone writes the sentence."""
    return re.fullmatch(r"<[^<>]*>", text) is not None


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
    said = without_comments("\n".join(section(lines, "outcome"))).splitlines()
    outcome = next((plain(" ".join(p)[:PARAGRAPH_MAX]) for p in paragraphs(said)
                    if not (HEADING.match(p[0]) or HTML_BLOCK.match(p[0]))), "")
    outcome = "" if bare_tag(outcome) else outcome
    return outcome, {"status": status, "progress": progress}


# ------------------------------------------------------------- the repository

OPENS = re.compile(r"`[^`\n]+`|<!--")
FRONT_MATTER = re.compile(r"\A\s*---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.DOTALL)
INCLUDE = re.compile(r"^\s*@\S+\s*$")
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
SETEXT = re.compile(r"^\s*(=+|-+)\s*$")
NOT_PROSE = re.compile(r"^(\s{4,}|\t|[-*+]\s|\d+[.)]\s|\||>)")
# What starts a block in the middle of a paragraph, so the paragraph ends
# before it: a list (a numbered one only from 1) or a quote.
INTERRUPTS = re.compile(r"^\s{0,3}([-*+]\s|1[.)]\s|>)")
TAGS = re.compile(r"<[^>]*>")
# A line that opens an HTML block, which runs to the next blank line and is
# skipped whole: a block-level tag, a linked image, or a line that is one
# tag and nothing else.
BLOCK_TAGS = ("address|article|aside|blockquote|center|dd|details|dialog|div|dl|dt|fieldset|figcaption|figure|"
              "footer|form|h[1-6]|header|hr|iframe|img|li|main|menu|nav|ol|p|picture|pre|script|section|style|"
              "summary|table|tbody|td|th|thead|tr|ul|video")
HTML_BLOCK = re.compile(rf"^\s{{0,3}}(?:</?(?:{BLOCK_TAGS})(?:[\s/>]|$)|<a\b[^<>]*>\s*<img\b|<[A-Za-z][^<>]*>\s*$)",
                        re.IGNORECASE)
# README, then the instructions for agents, then Claude's own: AGENTS.md is
# the file a project writes about itself, CLAUDE.md often only includes it.
DESCRIBED_BY = (("readme.md", "readme.markdown", "readme.txt", "readme"),
                ("agents.md",), ("claude.md",))


def without_comments(text):
    """The text with its HTML comments taken out. One that never closes runs to
    the end, as it does when the README is shown. A code span on a line is
    code: a `<!--` inside it opens nothing. The end of a comment is found with
    `find`, not a pattern: a pattern tries every `<!--` against the whole rest
    of the file."""
    out, at = [], 0
    while True:
        found = OPENS.search(text, at)
        if found is None:
            out.append(text[at:])
            return "".join(out)
        if found.group() != "<!--":                 # a code span goes by as it stands
            out.append(text[at:found.end()])
            at = found.end()
            continue
        out.append(text[at:found.start()])
        end = text.find("-->", found.end())
        if end < 0:
            return "".join(out)
        at = end + 3


def prose(par):
    """The text of a paragraph that is prose, or "" when it is a heading,
    a list, a table, a quote, code, a badge row, an HTML block or an
    include."""
    for i, line in enumerate(par):                  # a title with its underline, dashes too
        if i and SETEXT.match(line):
            par = par[i + 1:]
            break
    par = [line for line in par if not (INCLUDE.match(line) or REFERENCE.match(line)
                                        or RULE.match(line))]
    if not par or HEADING.match(par[0]) or NOT_PROSE.match(par[0]) or HTML_BLOCK.match(par[0]):
        return ""
    par = par[:next((i for i, line in enumerate(par)
                     if i and (INTERRUPTS.match(line) or HTML_BLOCK.match(line))), len(par))]
    raw = " ".join(par)[:PARAGRAPH_MAX]
    text = plain(raw)
    return "" if bare_tag(text) or not has_words(raw) else text


def has_words(raw):
    """Whether markdown has words of its own: not only links, badges and tags,
    like a row of badges or the switcher between a README's languages."""
    rest = HTML_LINK.sub("", LINK.sub("", IMAGE.sub("", raw)))
    return re.search(r"\w", TAGS.sub("", rest)) is not None


def first_prose(text):
    """The first paragraph of a markdown text that is prose, or ""."""
    text = without_comments(FRONT_MATTER.sub("", text, count=1))
    return next((got for got in map(prose, paragraphs(unfenced(text))) if got), "")


def files_in(folder):
    """The files directly in a folder, `{lowercase name: path}`."""
    try:
        with os.scandir(folder) as entries:
            return {e.name.casefold(): e.path for e in entries if e.is_file()}
    except OSError:
        return {}


def placed_in(cwd, project_id):
    """Whether a launch folder is in this repository by where it is, whatever
    the person has assigned its session to."""
    project = projects.project_of(cwd, lambda _: None)
    return bool(project) and project["id"] == project_id


def repository_text(rows, project_id):
    """What the repository says about itself: the first prose of its README,
    else of its agent instructions. Read from the main checkout when it is
    there, so that the line is the same whichever worktree a session is in
    and whichever session comes first. A session assigned here from another
    repository lends nothing: its folder is not this repository's."""
    roots = {}
    for cwd in sorted({m["cwd"] for m in rows if placed_in(m["cwd"], project_id)}):
        for rank, root in enumerate(projects.checkouts(cwd)):
            roots[root] = min(rank, roots.get(root, rank))
    here = {root: files_in(root) for root in sorted(roots, key=lambda r: (roots[r], str(r)))}
    # The kind of file decides first, the checkout only between files of one kind.
    for wanted in DESCRIBED_BY:
        for found in here.values():
            path = next((found[name] for name in wanted if name in found), None)
            text = first_prose(read(path)) if path else ""
            if text:
                return text
    return ""


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
        return line_from("own", own), track
    if outcome:
        return line_from("goal", first_sentence(outcome), outcome), track
    about = repository_text(rows, project["id"]) if project["kind"] == "repository" else ""
    if about:
        return line_from("readme", about), track
    return line_from("guess", guess(rows)), track
