#!/usr/bin/env python3
"""Every interactive conversation, searchable by keyword.

**⟲ closed N** only knows this boot. This keeps an index of every
interactive Claude Code conversation on the machine -- running ones included
-- so the page can find one from last week by what was said in it.

One passage is one exchange: a prompt you typed and the text of the
assistant's reply. Tool calls and their results, thinking, `<system-reminder>`
blocks and hook injections are left out; they are most of a transcript by
weight and none of what you would remember it by. A turn someone else started
(a peer's message, a finished background task) begins an exchange of its own
with an empty prompt, so a passage always points at one moment.

The index is one SQLite file (FTS5) under `~/.claude/agentview/`. Nothing
leaves the machine. A timer runs `archive.py update` every few minutes; it
reads only transcripts whose size or mtime moved, and only from the start of
their last exchange -- the one that may still be growing.

    archive.py update          index what changed (the timer runs this)
    archive.py search WORDS    what the page's search box would show
    archive.py stats           what the index holds, and how the last run went

Schema (version 3). Change it by bumping SCHEMA_VERSION: the index is derived
from the transcripts, so a version it does not know is rebuilt from scratch.

    conversations  one row per transcript: id (the session id), path, cwd,
                   name, title, started, active, and where reading stopped
                   (size, mtime, tail, exchanges, and mark: a hash of all
                   the bytes up to and including the line at the tail, to
                   tell an append from a rewrite)
    passages       id, conversation, exchange, piece, at, uuid, prompt, reply
                   -- (conversation, exchange, piece) is unique
    passages_fts   FTS5 over passages(prompt, reply), kept in step by triggers
    skipped        transcripts that are not interactive, never read again
    meta           schema version, and what the last run did

A passage's id changes when its exchange is read again, which happens only to
the last exchange of a conversation that is still growing. Anything keyed on
passage ids (vectors, ticket 04) should drop with the passage.
"""
import datetime
import fcntl
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import log
from providers import claude, registry

SCHEMA_VERSION = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
    id        TEXT PRIMARY KEY,
    path      TEXT NOT NULL,
    cwd       TEXT NOT NULL DEFAULT '',
    name      TEXT NOT NULL DEFAULT '',
    title     TEXT NOT NULL DEFAULT '',
    started   TEXT NOT NULL DEFAULT '',
    active    TEXT NOT NULL DEFAULT '',
    size      INTEGER NOT NULL DEFAULT 0,
    mtime     REAL NOT NULL DEFAULT 0,
    tail      INTEGER NOT NULL DEFAULT 0,
    exchanges INTEGER NOT NULL DEFAULT 0,
    mark      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS skipped (
    path       TEXT PRIMARY KEY,
    entrypoint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    id           INTEGER PRIMARY KEY,
    conversation TEXT NOT NULL,
    exchange     INTEGER NOT NULL,
    piece        INTEGER NOT NULL,
    at           TEXT NOT NULL DEFAULT '',
    uuid         TEXT NOT NULL DEFAULT '',
    prompt       TEXT NOT NULL DEFAULT '',
    reply        TEXT NOT NULL DEFAULT '',
    UNIQUE (conversation, exchange, piece)
);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    prompt, reply, content='passages', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2', prefix='2 3');
CREATE TRIGGER IF NOT EXISTS passages_added AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, prompt, reply) VALUES (new.id, new.prompt, new.reply);
END;
CREATE TRIGGER IF NOT EXISTS passages_removed AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, prompt, reply)
    VALUES ('delete', old.id, old.prompt, old.reply);
END;
"""

# The embedder that ticket 04 feeds takes 2,048 tokens a text. Three
# characters a token is pessimistic for prose and about right for code, so
# a piece this long fits either way.
PIECE = 6000

# Machine text inside a prompt: reminders Claude Code adds, and what hooks
# inject. Neither is you speaking.
INJECTED = re.compile(r"<(system-reminder|user-prompt-submit-hook)>.*?</\1>", re.S)
PASTED = re.compile(r"</?pasted_content\b[^>]*>")
COMMAND = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)

# Recent Claude Code says who wrote a user record in `origin`. Records from
# before that, and local commands, carry none and are told apart by how they
# begin.
NOT_TYPED = ("<local-command-", "<bash-", "<command-name>", "<command-message>",
             "[Request interrupted", "<teammate-message", "<cross-session-message")
TURN_OPENERS = ("Another Claude session sent a message", "<task-notification>")
TURN_ORIGINS = ("peer", "task-notification")


def db_path():
    return claude.claude_dir() / "agentview" / "archive.db"


def projects_dir():
    return claude.claude_dir() / "projects"


# ------------------------------------------------------------ reading one

def _user_text(content):
    """A user record's text, or None for a tool result."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
            return None
        return "\n".join(p["text"] for p in content if isinstance(p, dict)
                         and p.get("type") == "text" and isinstance(p.get("text"), str))
    return None


def opens(rec):
    """Whether a record begins an exchange: "typed" for a prompt you typed,
    "turn" for a turn someone else started, None for everything else."""
    if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isCompactSummary"):
        return None
    text = _user_text((rec.get("message") or {}).get("content"))
    if text is None:
        return None
    origin = rec.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind:
        return "typed" if kind == "human" else "turn" if kind in TURN_ORIGINS else None
    if rec.get("isMeta"):
        return None
    head = text.lstrip()
    if head.startswith(TURN_OPENERS):
        return "turn"
    if not head or head.startswith(NOT_TYPED):
        return None
    return "typed"


def prompt_text(rec):
    """What you typed, as you would remember typing it."""
    text = INJECTED.sub("", _user_text((rec.get("message") or {}).get("content")) or "")
    cmd = COMMAND.search(text)
    if cmd:
        # `/rem some words`, not the markup Claude Code wraps it in.
        args = ARGS.search(text)
        text = cmd.group(1) + (" " + args.group(1).strip() if args and args.group(1).strip() else "")
    return PASTED.sub("", text).strip()


def reply_text(rec):
    """The words of an assistant record: no thinking, no tool calls."""
    if rec.get("type") != "assistant" or rec.get("isSidechain") or rec.get("isApiErrorMessage"):
        return ""
    msg = rec.get("message") or {}
    if msg.get("model") == "<synthetic>":
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [p["text"] for p in content if isinstance(p, dict)
                 and p.get("type") == "text" and isinstance(p.get("text"), str)]
    else:
        return ""
    return INJECTED.sub("", "\n".join(parts)).strip()


def read_lines(path, offset):
    """Complete lines from `offset` on, each with the offset it starts at.
    A line still being written is left for the next run."""
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    at = 0
    while (end := data.find(b"\n", at)) >= 0:
        yield offset + at, data[at:end]
        at = end + 1


def parse(lines):
    """Turn transcript lines into exchanges, plus what the lines said about
    the conversation itself: where it ran, when, and under what name."""
    exchanges, facts, cur = [], {"cwd": "", "first": "", "last": "", "named": ""}, None
    for offset, raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        stamp = rec.get("timestamp")
        if isinstance(stamp, str) and stamp:
            facts["first"] = facts["first"] or stamp
            facts["last"] = max(facts["last"], stamp)
        if not facts["cwd"] and isinstance(rec.get("cwd"), str):
            facts["cwd"] = rec["cwd"]
        if rec.get("type") == "agent-name" and isinstance(rec.get("agentName"), str):
            facts["named"] = rec["agentName"]
        kind = opens(rec)
        if kind:
            cur = {"offset": offset, "at": stamp or "", "uuid": rec.get("uuid") or "",
                   "prompt": prompt_text(rec) if kind == "typed" else "", "reply": []}
            exchanges.append(cur)
            continue
        said = reply_text(rec)
        if said:
            if cur is None:
                # Words before anything started a turn: an exchange all the same.
                cur = {"offset": offset, "at": stamp or "", "uuid": rec.get("uuid") or "",
                       "prompt": "", "reply": []}
                exchanges.append(cur)
            cur["reply"].append(said)
    for ex in exchanges:
        ex["reply"] = "\n\n".join(ex["reply"])
    return exchanges, facts


def pieces(prompt, reply, size=PIECE):
    """Cut an exchange into pieces of at most `size` characters, each with
    the part of the prompt and the part of the reply that fall inside it."""
    sep = "\n\n"
    whole = prompt + sep + reply
    if len(whole) <= size:
        return [(prompt, reply)]
    off, cuts, start = len(prompt) + len(sep), [], 0
    while start < len(whole):
        end = min(start + size, len(whole))
        if end < len(whole):
            # Break on whitespace when there is some in the back half.
            space = max(whole.rfind(c, start + size // 2, end) for c in " \n")
            end = space + 1 if space > start else end
        cuts.append((start, end))
        start = end
    return [(prompt[a:min(b, len(prompt))].strip(),
             reply[max(a - off, 0):max(b - off, 0)].strip()) for a, b in cuts]


def fingerprint(path, tail, line=65536):
    """A hash of everything already read: the bytes before the resume point
    and the line there. A transcript only ever grows, so if this changed it
    was rewritten. Appends come after the resume line and never touch it.
    Costs one read of the file, as the title reader already does."""
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        left = tail
        while left > 0 and (chunk := fh.read(min(left, 1 << 20))):
            digest.update(chunk)
            left -= len(chunk)
        digest.update(b"\0" + fh.read(line).split(b"\n", 1)[0])
    return digest.hexdigest()


def entrypoint(path, lines=400):
    """What started the conversation: `cli` for a terminal, `sdk-cli` for
    `claude -p`. None until the transcript has said."""
    try:
        with open(path, "rb") as fh:
            for _, raw in zip(range(lines), fh):
                if b'"entrypoint"' in raw:
                    try:
                        return json.loads(raw).get("entrypoint")
                    except ValueError:
                        continue
    except OSError:
        pass
    return None


# ------------------------------------------------------------ the index

def connect(path=None):
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    # The index holds prompts verbatim, as private as the transcripts it
    # comes from (0600). SQLite gives its -wal and -shm the file's mode.
    path.touch(mode=0o600)
    for f in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if f.exists() and f.stat().st_mode & 0o077:
            f.chmod(0o600)
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    have = None
    try:
        have = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    except sqlite3.OperationalError:
        pass
    if have and have[0] != SCHEMA_VERSION:
        # Derived data: a schema this code does not know is rebuilt, not migrated.
        for kind, name in con.execute("SELECT type, name FROM sqlite_master WHERE type IN "
                                      "('table','trigger') AND name NOT LIKE 'sqlite_%' "
                                      "AND name NOT LIKE 'passages_fts_%'").fetchall():
            con.execute(f"DROP {kind} IF EXISTS {name}")
        have = None
    con.executescript(SCHEMA)
    if not have:
        con.execute("INSERT INTO passages_fts(passages_fts, rank) VALUES ('rank', 'bm25(2.0, 1.0)')")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
        con.commit()
    return con


def index_file(con, path, sid):
    """Bring one transcript's passages up to date. True if anything was read."""
    st = path.stat()
    row = con.execute("SELECT size, mtime, tail, exchanges, mark FROM conversations WHERE id=?",
                      (sid,)).fetchone()
    if row and (row[0], row[1]) == (st.st_size, st.st_mtime):
        return False
    if row and (st.st_size <= row[0] or fingerprint(path, row[2]) != row[4]):
        # Touched without growing, or grown from something other than what
        # was read: rewritten, not appended to. Start over, so nothing that
        # is no longer in the transcript stays findable.
        con.execute("DELETE FROM passages WHERE conversation=?", (sid,))
        con.execute("DELETE FROM conversations WHERE id=?", (sid,))
        row = None
    tail, done = (row[2], row[3]) if row else (0, 0)
    exchanges, facts = parse(read_lines(path, tail))
    # The exchange at the tail was open last time; read again, it replaces itself.
    con.execute("DELETE FROM passages WHERE conversation=? AND exchange>=?", (sid, done))
    for n, ex in enumerate(exchanges, start=done):
        for k, (p, r) in enumerate(pieces(ex["prompt"], ex["reply"])):
            if p or r:
                con.execute("INSERT INTO passages (conversation, exchange, piece, at, uuid, prompt, reply)"
                            " VALUES (?,?,?,?,?,?,?)", (sid, n, k, ex["at"], ex["uuid"], p, r))
    if exchanges:
        tail, done = exchanges[-1]["offset"], done + len(exchanges) - 1
    title, mark = claude.last_title(path), fingerprint(path, tail)
    if row:
        con.execute("UPDATE conversations SET path=?, title=?, size=?, mtime=?, tail=?, exchanges=?, mark=?,"
                    " cwd=CASE WHEN cwd='' THEN ? ELSE cwd END,"
                    " started=CASE WHEN started='' THEN ? ELSE started END,"
                    " active=MAX(active, ?),"
                    " name=CASE WHEN ?<>'' THEN ? ELSE name END WHERE id=?",
                    (str(path), title, st.st_size, st.st_mtime, tail, done, mark, facts["cwd"],
                     facts["first"], facts["last"], facts["named"], facts["named"], sid))
    else:
        con.execute("INSERT INTO conversations (id, path, cwd, name, title, started, active,"
                    " size, mtime, tail, exchanges, mark) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, str(path), facts["cwd"], facts["named"], title, facts["first"],
                     facts["last"], st.st_size, st.st_mtime, tail, done, mark))
    return True


def peer_names(cfg=None):
    """The name each session last ran under, from Claude Code's peer files --
    the same place the page reads a live session's name from."""
    got = {}
    for rec in registry.records(cfg):
        sid, name = rec.get("sessionId"), rec.get("name")
        if isinstance(sid, str) and isinstance(name, str) and name:
            when = rec.get("updatedAt") or 0
            if sid not in got or when >= got[sid][0]:
                got[sid] = (when, name)
    return {sid: name for sid, (_, name) in got.items()}


def logged_names(paths=None):
    """Names agentview's own log saw sessions under. Read oldest first, so
    the newest name wins. A peer file goes when its session ends; this
    remembers the name for as long as the log goes back."""
    got = {}
    for path in paths or (log.LOG.with_suffix(".jsonl.1"), log.LOG):
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"sessionId"' not in line or '"name"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                sid, name = rec.get("sessionId"), rec.get("name")
                if isinstance(sid, str) and isinstance(name, str) and name:
                    got[sid.partition(":")[2] if sid.startswith("claude:") else sid] = name
    return got


class Names:
    """The name a conversation last had. A peer file, while it lasts, is the
    truth; after that the log. When neither knows, whatever Claude Code wrote
    into the transcript stands, and failing that the name already stored.
    Each source is read at most once a run, and only if it is needed."""

    def __init__(self, cfg=None, logs=None):
        self.cfg, self.logs, self.peers, self.logged = cfg, logs, None, None

    def __call__(self, sid):
        if self.peers is None:
            self.peers = peer_names(self.cfg)
        if sid in self.peers:
            return self.peers[sid]
        if self.logged is None:
            self.logged = logged_names(self.logs)
        return self.logged.get(sid, "")


def update(path=None, root=None, cfg=None, logs=None, say=lambda *_: None):
    """Index every interactive transcript that changed since the last run."""
    began = time.monotonic()
    con = connect(path)
    root = Path(root or projects_dir())
    skipped = dict(con.execute("SELECT path, entrypoint FROM skipped"))
    known = {r[0] for r in con.execute("SELECT id FROM conversations")}
    files = sorted(root.glob("*/*.jsonl"))
    changed, seen, names = [], set(), Names(cfg, logs)
    for f in files:
        key = str(f)
        if key in skipped:
            continue
        sid = f.stem
        if sid in seen:
            continue                      # one id, one transcript; never seen two, never thrash
        if sid not in known:
            ep = entrypoint(f)
            if ep is None:
                continue                  # too new to say; next run
            if ep != "cli":
                con.execute("INSERT OR REPLACE INTO skipped VALUES (?, ?)", (key, ep))
                con.commit()
                continue
        seen.add(sid)
        try:
            if index_file(con, f, sid):
                changed.append(sid)
                name = names(sid)
                if name:
                    con.execute("UPDATE conversations SET name=? WHERE id=?", (name, sid))
                con.commit()
                say(f"  {len(changed)}  {f.name}")
        except OSError:
            con.rollback()                # gone between the listing and the read
    # A session renamed while its transcript sat still: the new name is in
    # its peer file, or in the log once that file is gone. Every conversation
    # is asked, not only the ones that changed; an empty answer keeps what
    # is stored.
    stored = dict(con.execute("SELECT id, name FROM conversations"))
    renamed = [(name, sid) for sid in stored if sid in seen
               and (name := names(sid)) and name != stored[sid]]
    con.executemany("UPDATE conversations SET name=? WHERE id=?", renamed)
    # A transcript that is gone cannot be reopened, so it cannot be found.
    # An empty listing is a missing directory, not an empty history.
    if files:
        present = {str(f) for f in files}
        for sid in known - seen:
            p = con.execute("SELECT path FROM conversations WHERE id=?", (sid,)).fetchone()
            if p and p[0] not in present:
                con.execute("DELETE FROM passages WHERE conversation=?", (sid,))
                con.execute("DELETE FROM conversations WHERE id=?", (sid,))
        con.executemany("DELETE FROM skipped WHERE path=?",
                        [(p,) for p in skipped if p not in present])
    run = {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "files": len(files),
           "conversations": con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
           "changed": len(changed),
           "passages": con.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
           "seconds": round(time.monotonic() - began, 2)}
    con.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)", (json.dumps(run),))
    con.commit()
    con.close()
    return run


# ------------------------------------------------------------ searching

WORD = re.compile(r'"([^"]*)"|(\S+)')


def fts_query(words):
    """What you typed, as an FTS5 query that cannot be a syntax error: every
    word quoted, all of them required, the last one a prefix while you are
    still typing it. "A phrase in quotes" stays a phrase."""
    terms = []
    for phrase, word in WORD.findall(words or ""):
        text = (phrase or word).strip()
        if re.search(r"\w", text):
            terms.append((text, bool(phrase)))
    if not terms:
        return ""
    quoted = ['"' + t.replace('"', '""') + '"' for t, _ in terms]
    # A prefix from three characters on: a one-letter prefix matches half
    # the index and takes the better part of a second.
    last, phrase = terms[-1]
    if not phrase and len(last) >= 3:
        quoted[-1] += "*"
    return " ".join(quoted)


def search(words, limit=30, path=None, live=()):
    """Conversations matching every word, best first, each with the passage
    that matched best. None when there is no index yet."""
    query = fts_query(words)
    path = Path(path or db_path())
    if not path.exists():
        return None
    if not query:
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        # One row per conversation, carrying its best passage: with a single
        # MIN() in the query, SQLite takes the bare p.id from the row that
        # holds the minimum. Grouped here rather than after a LIMIT, so one
        # conversation with a thousand hits cannot crowd out the others.
        best = {conv: rowid for conv, rowid, _ in con.execute(
            "SELECT p.conversation, p.id, MIN(passages_fts.rank) AS score"
            " FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid"
            " WHERE passages_fts MATCH ? GROUP BY p.conversation ORDER BY score LIMIT ?",
            (query, limit))}
        if not best:
            return []
        marks = ",".join("?" * len(best))
        quoted = {r[0]: r[1:] for r in con.execute(
            "SELECT p.id, p.exchange, p.piece, p.at, p.uuid,"
            " snippet(passages_fts, 0, char(2), char(3), '…', 16),"
            " snippet(passages_fts, 1, char(2), char(3), '…', 32)"
            f" FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid"
            f" WHERE passages_fts MATCH ? AND passages_fts.rowid IN ({marks})",
            (query, *best.values()))}
        about = {r[0]: r[1:] for r in con.execute(
            f"SELECT id, name, title, cwd, started, active FROM conversations WHERE id IN ({marks})",
            tuple(best))}
    finally:
        con.close()
    out = []
    for conv, rowid in best.items():
        if conv not in about or rowid not in quoted:
            continue
        name, title, cwd, started, active = about[conv]
        exchange, piece, at, uuid, prompt, reply = quoted[rowid]
        out.append({"id": conv, "name": name, "title": title, "cwd": cwd,
                    "started": started, "active": active, "live": conv in live,
                    "passage": {"exchange": exchange, "piece": piece, "at": at, "uuid": uuid,
                                "prompt": prompt, "reply": reply}})
    return out


def stats(path=None):
    path = Path(path or db_path())
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        run = con.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
        return {"conversations": con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                "passages": con.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
                "last_run": json.loads(run[0]) if run else None}
    finally:
        con.close()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "update"
    if cmd == "update":
        lock = db_path().with_suffix(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                print("another update is running")
                return 0
            verbose = "-v" in argv
            run = update(say=print if verbose else (lambda *_: None))
        print(f"{run['changed']} of {run['conversations']} conversations read, "
              f"{run['passages']} passages, {run['seconds']}s")
        return 0
    if cmd == "search":
        live = {r.get("sessionId") for r in registry.live()}
        hits = search(" ".join(argv[2:]), live=live)
        if hits is None:
            print("no index yet: run archive.py update")
            return 1
        for h in hits:
            quote = (h["passage"]["reply"] or h["passage"]["prompt"]).replace("\x02", "[").replace("\x03", "]")
            print(f"{h['active'][:16]}  {h['name'] or h['id'][:8]:<14} {h['title'][:60]}")
            print(f"{'':18}{' '.join(quote.split())[:110]}")
        return 0
    if cmd == "stats":
        print(json.dumps(stats(), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
