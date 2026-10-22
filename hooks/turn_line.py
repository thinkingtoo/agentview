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
PASTE = HERE / "paste"

ASK = """Before this turn ends, run this once, as your last action:

{writer} {sid} --did '<one short sentence: where the work stands>' --n <number> \
--ask '<the one thing you are blocked on -- only when the number is 1>'

It feeds the dashboard that shows every running session. Write both fields in \
the language of this conversation, in plain text (single quotes, no backticks). \
A command the user must run goes inside double quotes, or after "$ " at the end \
of the ask, within the single-quoted text. A single quote in either field is \
written as '\\''. --n is how many things are left for the user when this turn ends: a decision, \
a command for them to run, a mail for them to send, a sign-in. Count them even \
when you have other work, since nothing moves on them once you stop. An offer \
(want me to...?) is none. Do not mention having run it.

Text the user must paste elsewhere goes on their card, not the clipboard, unless \
they ask for the clipboard in so many words (then use it). Put it in a file in a \
private place (the session scratchpad, else a mktemp -d directory; never the repo \
or /tmp at large), then run {paste} create {sid} <file> --title '<short>' \
--provider claude (add --secret for a password, token or key, then delete the \
file). It prints the id; name the title in your reply. A Paste counts in --n. \
Withdraw it only once you have seen it used (the mail is sent): {paste} withdraw \
{sid} <id> --provider claude. If paste create is refused (by the classifier or by an \
error), say so in the --ask line and put the text itself in your question or reply; \
never stay silent. A command the user must type goes in the --ask line after "$ " too, \
even when an option of your question offers it, without a leading !."""


def begin(payload, root=None):
    """Forget the last line, start a turn, and say what to run this turn."""
    sid = payload.get("session_id")
    if not sid:
        return {}
    lines.begin_turn(sid, root)
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ASK.format(writer=WRITER, paste=PASTE, sid=sid)}}


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
