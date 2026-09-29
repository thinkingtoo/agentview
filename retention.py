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
import stat
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from providers import claude  # noqa: E402

HEADLESS = "sdk-cli"
DAYS = 30
MAX_LINE = 64 * 1024 * 1024     # the largest line here is 1.5 MB; more is not read
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _headless(fh):
    """True only if the file reads cleanly and every record naming an
    entrypoint says sdk-cli. A line that does not parse could have been the
    one that said cli, so it keeps the transcript."""
    seen = False
    try:
        while True:
            line = fh.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                return False
            record = json.loads(line)
            if not isinstance(record, dict):
                return False
            entry = record.get("entrypoint")
            if entry is None:
                continue
            if entry != HEADLESS:
                return False
            seen = True
    except (ValueError, RecursionError, MemoryError):
        # Not enough memory to read a line is not enough to say it was not cli.
        return False
    return seen


def _lstat(name, fd):
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same(a, b):
    return (a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns)


def _judge(name, fd, cutoff):
    """The transcript's stat if it is expired and headless, else None.
    Nothing here follows a link: a transcript or session folder that is one
    is not a candidate."""
    st = _lstat(name, fd)
    if st is None or not stat.S_ISREG(st.st_mode) or st.st_mtime >= cutoff:
        return None
    folder = _lstat(name[:-len(".jsonl")], fd)
    if folder is not None and not stat.S_ISDIR(folder.st_mode):
        return None
    with os.fdopen(os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd), "rb") as fh:
        if not _same(os.fstat(fh.fileno()), st):
            return None
        return st if _headless(fh) else None


def _refuse(err):
    raise err


def _check_deletable(name, fd):
    """Raise unless the whole folder can be deleted, before anything in it is.
    rmtree is not transactional: stopped halfway it leaves files gone that no
    rollback brings back. So look first, in one walk: every directory must be
    readable, writable and searchable, and none may be another filesystem
    (rmtree walks into a mount and empties it before it fails on the mount
    point)."""
    dev = os.stat(name, dir_fd=fd, follow_symlinks=False).st_dev
    for dirpath, dirs, _, dir_fd in os.fwalk(name, dir_fd=fd, onerror=_refuse):
        if not os.access(".", os.R_OK | os.W_OK | os.X_OK, dir_fd=dir_fd):
            raise OSError(f"{dirpath} in its session folder cannot be emptied")
        for d in dirs:
            if os.stat(d, dir_fd=dir_fd, follow_symlinks=False).st_dev != dev:
                raise OSError("another filesystem is mounted inside its session folder")


def _put_file_back(tmp, name, fd):
    """Undo a rename without overwriting whatever took the name meanwhile:
    a hard link fails if the name exists, where a rename would replace it."""
    try:
        os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    except OSError:
        return False
    try:
        os.unlink(tmp, dir_fd=fd)
    except OSError:
        pass            # restored; the file just has a second name for now
    return True


def _put_folder_back(tmp, name, fd):
    """A folder renamed onto a name that is taken fails, unless what took it
    is an empty folder, which it replaces: nothing is lost either way."""
    try:
        os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
    except OSError:
        return False
    return True


def _remove(name, fd, judged, path, warn):
    """Delete one transcript and its session folder, or leave both as they
    were. Claude Code appends to a transcript by path and holds no handle
    open (15 running sessions checked, 2026-09-29), so once the transcript is
    renamed nothing can write to it: a resume that arrives now starts a new
    file under the old name, which is never touched."""
    sid = name[:-len(".jsonl")]
    # A rename replaces a file that already has the new name, so the name is
    # one nothing else can have: not a leftover of an earlier run, and not
    # one guessed in advance.
    tag = f".retention-{uuid.uuid4().hex}"
    try:
        os.rename(name, name + tag, src_dir_fd=fd, dst_dir_fd=fd)
    except OSError as err:
        warn(f"kept {path}: {err}")
        return False
    try:
        now = _lstat(name + tag, fd)
        if now is None or not _same(now, judged):
            raise OSError("it changed while it was being judged")
        # Inode, size and mtime can be put back by whoever rewrote the file;
        # what it says cannot. Judge the renamed file's content once more.
        with os.fdopen(os.open(name + tag, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd), "rb") as fh:
            if not _headless(fh):
                raise OSError("it changed while it was being judged")
        folder = _lstat(sid, fd)
        if folder is not None:
            if not stat.S_ISDIR(folder.st_mode):
                raise OSError("its session folder became a link")
            os.rename(sid, sid + tag, src_dir_fd=fd, dst_dir_fd=fd)
            try:
                _check_deletable(sid + tag, fd)
                shutil.rmtree(sid + tag, dir_fd=fd)
            except Exception as err:
                if not _put_folder_back(sid + tag, sid, fd):
                    warn(f"left what remains of {path.with_suffix('')} as {sid + tag}")
                raise err
        os.unlink(name + tag, dir_fd=fd)
        return True
    except Exception as err:
        try:
            back = _put_file_back(name + tag, name, fd)
        except Exception:
            back = False
        if back:
            warn(f"kept {path}: {err}")
        else:
            warn(f"kept {path} as {name + tag}: {err}, and a new transcript took its name")
        return False


def _stderr(message):
    print(message, file=sys.stderr)


def _quiet(warn):
    """A warning that cannot be written (a closed pipe, a full journal) is
    lost; it must not stop the run or the rollback that was about to follow."""
    def call(message):
        try:
            warn(message)
        except Exception:
            pass
    return call


def prune(root, now, days=DAYS, dry_run=False, each=None, warn=_stderr):
    """Delete (or with dry_run, only name) the expired headless transcripts
    under root, each with its session folder. Returns the paths deleted.
    `each` is called with every one just before it goes; `warn` with every
    one that was judged expired and still kept.

    root itself may be a link, to another disk say; it is opened once and
    held. Below it every project is opened without following links and worked
    on through that handle, so a path swapped for a link meanwhile leads
    nowhere.

    Nothing that goes wrong with one transcript stops the run: each is
    handled on its own, and what fails is reported and left as it was."""
    gone = []
    warn = _quiet(warn)
    root = Path(root)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return gone
    try:
        try:
            projects = sorted(os.listdir(root_fd))
        except (OSError, MemoryError) as err:
            warn(f"could not list {root}: {err}")
            projects = []
        for project in projects:
            try:
                _prune_project(root, root_fd, project, now - days * 86400,
                               dry_run, each, warn, gone)
            except Exception as err:
                warn(f"skipped {root / project}: {err!r}")
    finally:
        os.close(root_fd)
    return gone


def _prune_project(root, root_fd, project, cutoff, dry_run, each, warn, gone):
    """Each deletion is appended to `gone` as it happens, so one that went
    through is reported even if a later one raises."""
    try:
        fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError:
        return
    try:
        try:
            names = sorted(os.listdir(fd))
        except (OSError, MemoryError) as err:
            warn(f"could not list {root / project}: {err}")
            names = []
        for name in names:
            # The session folder goes with the transcript, so the name has to
            # be a session id: never memory/, never anything else.
            if not (name.endswith(".jsonl") and SESSION_ID.fullmatch(name[:-len(".jsonl")])):
                continue
            path = root / project / name
            try:
                judged = _judge(name, fd, cutoff)
            except OSError:
                continue            # gone since it was listed
            except Exception as err:
                warn(f"kept {path}: {err!r}")
                continue
            if judged is None:
                continue
            try:
                if each:
                    each(path)
                if dry_run or _remove(name, fd, judged, path, warn):
                    gone.append(path)
            except Exception as err:
                warn(f"kept {path}: {err!r}")
    finally:
        os.close(fd)


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
