#!/usr/bin/env python3
"""Delete headless transcripts once they are 30 days old. Keep every other one.

Claude Code is told never to delete a transcript (`cleanupPeriodDays` set far
out in ~/.claude/settings.json), so every interactive conversation stays
reopenable. Headless `claude -p` runs are three quarters of the transcripts
and nobody reopens them; this deletes those, with their session folder
(subagent transcripts, spilled tool results), once untouched for 30 days.

    retention.py --dry-run        list what would go, delete nothing
    retention.py --delete         delete it

A transcript is headless only if every record that names an entrypoint says
`sdk-cli`. Anything else, a `cli` record, no entrypoint at all, a line that
does not parse, a file that cannot be read, is kept. So is one written to
while it was being judged, and one reached through a link.
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from providers import claude  # noqa: E402

HEADLESS = "sdk-cli"
DAYS = 30
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _headless(path):
    """True only if the file reads cleanly and every record naming an
    entrypoint says sdk-cli. A line that does not parse could have been the
    one that said cli, so it keeps the transcript."""
    seen = False
    with open(path, "rb") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                return False
            if not isinstance(record, dict):
                return False
            entry = record.get("entrypoint")
            if entry is None:
                continue
            if entry != HEADLESS:
                return False
            seen = True
    return seen


def _linked(path):
    folder = path.with_suffix("")
    return path.parent.is_symlink() or path.is_symlink() or folder.is_symlink()


def _judge(path, cutoff):
    """The transcript's stat if it is expired and headless, else None."""
    # The session folder is removed with the transcript, so the name has to
    # be a session id: never memory/, never anything a link leads to.
    if not SESSION_ID.fullmatch(path.stem) or _linked(path):
        return None
    try:
        st = path.stat()
        return st if st.st_mtime < cutoff and _headless(path) else None
    except OSError:
        return None


def _stderr(message):
    print(message, file=sys.stderr)


def prune(root, now, days=DAYS, dry_run=False, each=None, warn=_stderr):
    """Delete (or with dry_run, only name) the expired headless transcripts
    under root, each with its session folder. Returns the paths deleted.
    `each` is called with every one just before it goes; `warn` with every
    one that was judged expired and still kept."""
    gone = []
    for path in sorted(Path(root).glob("*/*.jsonl")):
        judged = _judge(path, now - days * 86400)
        if judged is None:
            continue
        if each:
            each(path)
        if dry_run:
            gone.append(path)
            continue
        # Judging reads the whole file. Anything written meanwhile, a resume
        # above all, means the verdict is about a file that no longer exists.
        try:
            st = path.lstat()
        except OSError as err:
            warn(f"kept {path}: {err}")
            continue
        if (st.st_ino, st.st_size, st.st_mtime_ns) != (
                judged.st_ino, judged.st_size, judged.st_mtime_ns) or _linked(path):
            warn(f"kept {path}: it changed while it was being judged")
            continue
        folder = path.with_suffix("")
        try:
            if folder.is_dir():
                shutil.rmtree(folder)
            path.unlink()
        except OSError as err:
            warn(f"kept {path}: {err}")
            continue
        gone.append(path)
    return gone


def _size(path):
    try:
        total = path.stat().st_size
        for dirpath, _, files in os.walk(path.with_suffix("")):
            total += sum(os.lstat(os.path.join(dirpath, f)).st_size for f in files)
        return total
    except OSError:
        return 0


def main(argv, now=None):
    if len(argv) != 2 or argv[1] not in ("--dry-run", "--delete"):
        print(__doc__)
        return 2
    dry = argv[1] == "--dry-run"
    seen, kept = {}, []

    def each(path):
        try:
            day = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        except OSError:
            day = "?"
        seen[path] = (day, _size(path))

    def warn(message):
        kept.append(message)
        _stderr(message)

    gone = prune(claude.claude_dir() / "projects", now or time.time(),
                 dry_run=dry, each=each, warn=warn)
    for path in gone:
        day, size = seen[path]
        print(f"{day}  {size / 1e6:8.1f} MB  {path}")
    noun = "headless transcript" if len(gone) == 1 else "headless transcripts"
    verb = "would delete" if dry else "deleted"
    freed = sum(seen[p][1] for p in gone) / 1e6
    print(f"{verb} {len(gone)} {noun} older than {DAYS} days, {freed:.1f} MB"
          + (f"; {len(kept)} kept after an error, see above" if kept else ""))
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
