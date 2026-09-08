#!/usr/bin/env python3
"""Check, at every stop, that the session said where it left things.

The asking happens at the start of the turn (`turn_line.py`), so by the time
a session stops it has usually already written its line as an ordinary action
inside the turn it was having. This only checks.

It used to do the asking itself, by returning `decision: block` so Claude Code
re-invoked the model for one more turn. That cost an extra turn at every stop
and -- worse -- Claude Code renders any Stop-hook block to the user under the
heading `Stop hook error:`, in every session on the machine, with no setting
to change it. So this blocks nothing now.

When the session did not write a line, the last thing it said is read for a
question and stored as an **unverified** fallback: it fills the words on the
card and never reaches the count, because extraction cannot tell a question
that stopped a session from one that offered to do more. When there is not
even that, the miss is recorded, so how often the instruction is followed is
a number you can look up rather than a feeling.

FAIL-OPEN. Every path exits 0, and none of them can keep a session from
stopping.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fleet          # noqa: E402  -- after the path is set
import lines          # noqa: E402
import log            # noqa: E402

# The end of the transcript. The last thing said is at the bottom of the file
# and these run to tens of megabytes.
TAIL = 256 * 1024

def last_said(text):
    """The newest thing the session itself said, out of a chunk of transcript.

    A subagent must never speak for the session it works for, and the first
    line of a tail read is usually cut in half.
    """
    said = ""
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (isinstance(part, dict) and part.get("type") == "text"
                    and isinstance(part.get("text"), str) and part["text"].strip()):
                said = part["text"].strip()
    return said


def decide(payload, said, root=None):
    """What this stop leaves behind: nothing, a fallback, or a recorded miss.

    Never blocks. `stop_hook_active` is not consulted because there is no
    second invocation to guard against.
    """
    sid = payload.get("session_id")
    if not sid:
        return {"action": "pass"}
    if lines.fresh(sid, root):
        return {"action": "pass"}
    ask, n = fleet.ask_from(said)
    if n:
        # `by="read"`: a guess with words in it. It fills the line and stays
        # out of the count -- only the session itself can say what stopped it.
        lines.write(sid, did="", ask=ask, n=n, by="read", root=root)
        return {"action": "write", "n": n}
    return {"action": "miss"}


def tail_of(path):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TAIL))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        said = last_said(tail_of(payload.get("transcript_path") or ""))
        got = decide(payload, said)
        if got["action"] != "pass":
            # Countable: `python3 log.py -k line` says how often a session
            # wrote its own line and how often this had to stand in.
            log.event("line", session=payload.get("session_id", "")[:8],
                      wrote=got["action"], asks=got.get("n", 0))
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
