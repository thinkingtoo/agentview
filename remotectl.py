"""Put a session under Remote Control from the phone.

On a phone the laptop's terminal is no use, and a session that never ran
`/remote-control` has no claude.ai link to open. This types the one command
into its tmux pane, under a name the server makes from the track and the role
(`chienvert-france-boss`, `chienvert-france-concierge`, `cross-track-Kenji`).
Nothing the page sends is ever typed: it names the session, and that is all.

It types only into a prompt that is waiting, empty, for a new message. A
session at work would take the command as a queued message, and a question
or a menu on screen would take the keys as an answer: on 2026-11-20 a `/rc`
sent by hand to a boss with a question open would have picked its first
option. Claude Code's own status says most of it; the screen says the rest.
"""
import re
import threading
import time

import jump

# Claude Code turns `/rc` into `/remote-control` itself.
COMMAND = "/rc"
NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
NAME_MAX = 60
WAIT = 15            # seconds the link is given to appear in the peer file
_BUSY = threading.Lock()
_STARTING = set()    # session ids a /rc was typed into and no link is back for yet


def name_for(s, concierge=False):
    """`<track>-boss`, `<track>-concierge`, or `<track>-<name>` for a worker.

    The track is the boss's tracker when the session is the boss, else the
    tmux session it runs in, without claude-boss's `boss-` prefix. A session
    in a tmux session with a bare number for a name has no track: its own name
    is the whole label."""
    tmux_session = str(s.get("tmux") or "").partition(":")[0]
    track = s.get("track") or ("" if tmux_session.isdigit() else tmux_session.removeprefix("boss-"))
    role = "boss" if s.get("boss") else "concierge" if concierge else str(s.get("name") or "")
    label = f"{track}-{role}" if track and role else track or role or "session"
    return NAME_CHARS.sub("-", label).strip("-")[:NAME_MAX] or "session"


def refusal(s):
    """Why a /rc must not be typed into this session now, or "" when it may."""
    if s.get("remote"):
        return ""
    if not s.get("tmux"):
        return "not in a tmux pane"
    if s.get("status") != "idle" or s.get("waitingFor"):
        return f"busy: {s.get('waitingFor') or s.get('status') or 'unknown'}"
    return ""


def prompt_is_empty(screen):
    """True when the last prompt on screen is Claude Code's input box, empty.

    The box is the `❯` line between two rules of `─`. A question shows `❯`
    before its first option, and a dialog draws no box at all: neither is
    empty-between-rules."""
    lines = screen.splitlines()
    at = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].lstrip().startswith("❯")), None)
    if at is None or at == 0 or at == len(lines) - 1:
        return False
    rule = lambda line: line.strip().startswith("─")
    empty = lines[at].replace(" ", " ").strip() == "❯"
    return empty and rule(lines[at - 1]) and rule(lines[at + 1])


def start(s, concierge=False, reread=None, run=jump._run, sleep=time.sleep, clock=time.monotonic):
    """Type `/rc <name>` into the session's pane and wait for its link.

    `reread()` returns the session as its peer file says now (None once it is
    gone). Returns {ok, url} or {ok: False, reason}."""
    if s.get("remote"):
        return {"ok": True, "url": s["remote"]}
    why = refusal(s)
    if why:
        return {"ok": False, "reason": why}
    sid = s.get("id")
    with _BUSY:
        if sid in _STARTING:
            return {"ok": False, "reason": "already starting"}
        _STARTING.add(sid)
    try:
        return _type_and_wait(s, concierge, reread, run, sleep, clock)
    finally:
        with _BUSY:
            _STARTING.discard(sid)


def _type_and_wait(s, concierge, reread, run, sleep, clock):
    pid = s.get("pid")
    pane = str(s.get("tmux") or "").rpartition(".")[2]
    # The pane is believed only when the shell tmux started there is an
    # ancestor of the session: pane ids repeat from one tmux server to the next.
    if not isinstance(pid, int) or not pane.startswith("%") or \
            jump.tmux_target(pid).rpartition(".")[2] != pane:
        return {"ok": False, "reason": "its tmux pane could not be confirmed"}
    shot = run(["tmux", "capture-pane", "-p", "-t", pane])
    if not shot or shot.returncode != 0:
        return {"ok": False, "reason": "could not read its screen"}
    if not prompt_is_empty(shot.stdout):
        return {"ok": False, "reason": "something is open on its screen"}
    name = name_for(s, concierge)
    typed = run(["tmux", "send-keys", "-t", pane, "-l", f"{COMMAND} {name}"])
    entered = typed and typed.returncode == 0 and run(["tmux", "send-keys", "-t", pane, "Enter"])
    if not entered or entered.returncode != 0:
        return {"ok": False, "reason": "could not type into its pane"}
    until = clock() + WAIT
    while clock() < until:
        sleep(0.5)
        now = reread() if reread else None
        if now and now.get("remote"):
            return {"ok": True, "url": now["remote"], "name": name}
    return {"ok": False, "reason": f"typed {COMMAND} {name}; no link yet", "name": name}
