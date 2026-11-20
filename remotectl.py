"""Put a session under Remote Control from the phone.

On a phone the laptop's terminal is no use, and a session that never ran
`/remote-control` has no claude.ai link to open. This types the one command
into its tmux pane, under a name the server makes from the track and the role
(`chienvert-france-boss`, `chienvert-france-concierge`, `cross-track-Kenji`).
Nothing the page sends is ever typed: it names the session, and that is all.

It never touches a session at work: Escape would interrupt it. Any other
session first gets an Escape, which closes a question, a menu or a dialog
(Thierry, 2026-11-20: Greta had a question open, and `/rc` reached her only
after an Escape; typed over the question, the keys would have picked its first
option). Then it types only into a prompt that is empty on screen, in a pane
that is not in copy mode and runs Claude in the foreground, and only when the
peer file, read again just before, still says the session is not busy.

`/rc` is a toggle: typed into a session already connected, it disconnects it.
So a session it was typed into is left alone for a while, even when its link
was slow to reach the peer file.
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
SETTLE = 0.5         # seconds an Escape is given to close what it closes
HOLD = 180           # seconds a session that was sent /rc is not sent it again
_BUSY = threading.Lock()
_TYPED = {}          # session id -> when a /rc was typed into it


def name_for(s, concierge=False):
    """`<track>-boss`, `<track>-concierge`, or `<track>-<name>` for a worker.

    The track is the boss's tracker when the session is the boss, else the
    tmux session it runs in, without claude-boss's `boss-` prefix. A session
    in a tmux session with a bare number for a name has no track: its own name
    is the whole label."""
    tmux_session = str(s.get("tmux") or "").partition(":")[0]
    track = s.get("track") or ("" if tmux_session.isdigit() else tmux_session.removeprefix("boss-"))
    name = str(s.get("name") or "")
    role = "boss" if s.get("boss") else "concierge" if concierge else "" if name == "(unnamed)" else name
    label = f"{track}-{role}" if track and role else track or role or "session"
    return NAME_CHARS.sub("-", label).strip("-")[:NAME_MAX] or "session"


def refusal(s):
    """Why a /rc must not be typed into this session now, or "" when it may."""
    if s.get("remote"):
        return ""
    if not s.get("tmux"):
        return "not in a tmux pane"
    if s.get("status") not in ("idle", "waiting"):
        return f"busy: {s.get('status') or 'unknown'}"
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
        if clock() - _TYPED.get(sid, -HOLD) < HOLD:
            return {"ok": False, "reason": "/rc was sent already; its link is on the way"}
        _TYPED[sid] = clock()
    out = _type_and_wait(s, concierge, reread, run, sleep, clock)
    if not out.get("name"):     # nothing was typed: the next tap may try again
        with _BUSY:
            _TYPED.pop(sid, None)
    return out


def _pane_ready(pane, run):
    """Why the pane would not hand typed keys to Claude, or ""."""
    got = run(["tmux", "display-message", "-p", "-t", pane, "#{pane_in_mode} #{pane_current_command}"])
    if not got or got.returncode != 0:
        return "could not read its pane"
    mode, _, command = got.stdout.strip().partition(" ")
    if mode != "0":
        return "its pane is scrolled back (copy mode)"
    if command != "claude":
        return f"its pane runs {command or 'nothing'} in front"
    return ""


def _type_and_wait(s, concierge, reread, run, sleep, clock):
    pid = s.get("pid")
    pane = str(s.get("tmux") or "").rpartition(".")[2]
    # The pane is believed only when the shell tmux started there is an
    # ancestor of the session: pane ids repeat from one tmux server to the next.
    if not isinstance(pid, int) or not pane.startswith("%") or \
            jump.tmux_target(pid).rpartition(".")[2] != pane:
        return {"ok": False, "reason": "its tmux pane could not be confirmed"}
    why = _pane_ready(pane, run)
    if why:
        return {"ok": False, "reason": why}
    escaped = run(["tmux", "send-keys", "-t", pane, "Escape"])
    if not escaped or escaped.returncode != 0:
        return {"ok": False, "reason": "could not type into its pane"}
    sleep(SETTLE)
    shot = run(["tmux", "capture-pane", "-p", "-t", pane])
    if not shot or shot.returncode != 0:
        return {"ok": False, "reason": "could not read its screen"}
    if not prompt_is_empty(shot.stdout):
        return {"ok": False, "reason": "something is still open on its screen"}
    # Claude draws the same empty box while it works: only the status says it
    # is not, and the one read before the Escape is too old to go by. A closed
    # question takes a moment to leave the peer file; a new turn does not.
    until = clock() + SETTLE * 6
    now = reread() if reread else s
    while now and now.get("status") == "waiting" and clock() < until:
        sleep(SETTLE)
        now = reread()
    if now and now.get("remote"):
        return {"ok": True, "url": now["remote"]}
    if not now or now.get("status") != "idle":
        return {"ok": False, "reason": f"busy: {(now or {}).get('status') or 'gone'}"}
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
