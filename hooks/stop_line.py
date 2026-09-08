#!/usr/bin/env python3
"""Ask a session, as it finishes, where it left things.

Claude Code writes a title and your last prompt. Neither answers the question
you have in front of thirteen cards -- where is this, and does it want
something from me -- because neither is written at the moment the session
stops. The session is the only thing that knows, so this asks it.

It asks only when it has to. If the session is already ending on a question,
its ask can be read straight out of the transcript and the hook writes that
line itself, silently: paying an extra turn to rewrite a line that is already
right is the wrong half of the cost. Only when nothing readable is there does
it block and put the question to the session.

FAIL-OPEN. Every path exits 0. A dashboard that does not know what a session
is doing is a small problem; a hook that stops a session from stopping is not.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fleet          # noqa: E402  -- after the path is set
import lines          # noqa: E402

# The end of the transcript. The last thing said is at the bottom of the file
# and these run to tens of megabytes.
TAIL = 256 * 1024

WRITER = HERE / "team-line"

INSTRUCTION = """Before you stop, say where this leaves things, for the dashboard \
that shows every running session. Run exactly this command, filling both fields \
in the language of this conversation:

{writer} {sid} --did "<where the work stands, one short sentence>" --n <number> \
--ask "<the one thing you are blocked on -- only when the number is 1>"

--n is how many things you need from the user before you can go further. Use 0 \
whenever you can carry on without them: a question you offered to answer \
yourself does not count, and neither does a suggestion. Use the real number \
when you are genuinely stopped until they answer.

Run the command, then stop. Do not explain it and do not do anything else."""


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
    """What to do about this stop: nothing, write the line, or ask for one."""
    sid = payload.get("session_id")
    if not sid:
        return {"action": "pass"}
    if payload.get("stop_hook_active"):
        # Asked once already. Whatever the session wrote -- or did not --
        # stands: blocking again is how a hook holds a session open forever.
        if lines.read(sid, root):
            return {"action": "pass"}
        ask, n = fleet.ask_from(said)
        if n:
            lines.write(sid, did="", ask=ask, n=n, root=root)
            return {"action": "write", "n": n}
        return {"action": "pass"}
    ask, n = fleet.ask_from(said)
    if n:
        lines.write(sid, did="", ask=ask, n=n, root=root)
        return {"action": "write", "n": n}
    return {"action": "block",
            "reason": INSTRUCTION.format(writer=WRITER, sid=sid)}


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
        if got["action"] == "block":
            json.dump({"decision": "block", "reason": got["reason"]}, sys.stdout)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
