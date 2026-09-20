#!/usr/bin/env python3
"""Start a turn: forget the last line, and ask for the next one.

Runs on `UserPromptSubmit`, which is the one moment that is unambiguously a
new turn. It does two things.

**Forgets the previous line.** The prompt you just typed is the answer to
whatever the session was blocked on, so keeping its line past this point
makes the page lie. This replaces a heuristic that watched for the session
going `busy` and dropped the line then -- which missed any turn that started
and finished between two polls of the page.

**Asks for the next one**, by injecting one short paragraph into the turn's
context. The session then writes its line as an ordinary action inside the
turn it was already having: no extra model turn, and nothing rendered to you
as an error. A Stop hook that blocks costs both, in every session on this
machine, at every stop.

FAIL-OPEN. Every path exits 0 and none of them blocks a prompt.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import lines          # noqa: E402  -- after the path is set

WRITER = HERE / "team-line"

ASK = """Before this turn ends, run this once, as your last action:

{writer} {sid} --did '<one short sentence: where the work stands>' --n <number> \
--ask '<the one thing you are blocked on -- only when the number is 1>'

It feeds the dashboard that shows every running session. Write both fields in \
the language of this conversation, in plain text (single quotes, no backticks). \
--n is how many things you need from the user before you can go further: 0 \
whenever you can carry on without them, since a question you offered to answer \
yourself is not a blocker. Do not mention having run it."""


def begin(payload, root=None):
    """Forget the last line, start a turn, and say what to run this turn."""
    sid = payload.get("session_id")
    if not sid:
        return {}
    lines.begin_turn(sid, root)
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ASK.format(writer=WRITER, sid=sid)}}


def main():
    # A headless `claude -p` run (routines, SDK) has no page line worth keeping, and the
    # instruction below would only cost it a denied tool call under its allowlist. Skip.
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            got = begin(payload)
            if got:
                json.dump(got, sys.stdout)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
