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
`sdk-cli`. Anything else, a `cli` record, no entrypoint at all, a file that
cannot be read, is kept.
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
    seen = False
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line).get("entrypoint")
            except (ValueError, AttributeError):
                continue
            if entry is None:
                continue
            if entry != HEADLESS:
                return False
            seen = True
    return seen


def _expired(path, cutoff):
    # The session folder is removed with the transcript, so the name has to
    # be a session id: never memory/, never anything a link leads to.
    folder = path.with_suffix("")
    if not SESSION_ID.fullmatch(folder.name):
        return False
    if path.parent.is_symlink() or path.is_symlink() or folder.is_symlink():
        return False
    try:
        return path.stat().st_mtime < cutoff and _headless(path)
    except OSError:
        return False


def prune(root, now, days=DAYS, dry_run=False, each=None):
    """Delete (or with dry_run, only name) the expired headless transcripts
    under root, each with its session folder. Returns their paths; `each` is
    called with every one just before it goes."""
    gone = []
    for path in sorted(Path(root).glob("*/*.jsonl")):
        if not _expired(path, now - days * 86400):
            continue
        gone.append(path)
        if each:
            each(path)
        if dry_run:
            continue
        folder = path.with_suffix("")
        if folder.is_dir():
            shutil.rmtree(folder)
        path.unlink()
    return gone


def _size(path):
    total = path.stat().st_size
    for dirpath, _, files in os.walk(path.with_suffix("")):
        total += sum(os.lstat(os.path.join(dirpath, f)).st_size for f in files)
    return total


def main(argv, now=None):
    if len(argv) != 2 or argv[1] not in ("--dry-run", "--delete"):
        print(__doc__)
        return 2
    dry = argv[1] == "--dry-run"
    freed = []

    def each(path):
        freed.append(_size(path))
        day = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        print(f"{day}  {freed[-1] / 1e6:8.1f} MB  {path}")

    gone = prune(claude.claude_dir() / "projects", now or time.time(), dry_run=dry, each=each)
    noun = "headless transcript" if len(gone) == 1 else "headless transcripts"
    verb = "would delete" if dry else "deleted"
    print(f"{verb} {len(gone)} {noun} older than {DAYS} days, {sum(freed) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
