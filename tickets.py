"""Open a GitHub ticket in Claude, from a link in the ticket itself.

A ticket on a wayfinder map carries a link to `/ticket/<owner>/<repo>/<n>` on
this server. Following it shows a page with the ticket and one button; the
button opens the conversation that belongs to the ticket. The first time, that
means a new Claude in a new WezTerm tab, started on the map with the ticket
named. Every time after, it means the same conversation: brought to the front
if it runs, resumed if it was closed.

Only repos listed under `ticket_repos` in config.json are served, each with the
directory its Claude starts in. The prompt is built here from the ticket's
number and its map; nothing in the URL ever reaches Claude as text. A GET only
shows the page: the launch is a POST, under the same local guard as every
other action.
"""
import html
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

PATH_RE = re.compile(r"^/ticket/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(\d{1,7})/?$")
WAYFINDER = "/mattpocock-skills:wayfinder"
MAP_LABEL = "wayfinder:map"


def route(path):
    """`/ticket/owner/repo/7` -> ("owner/repo", 7), anything else -> None."""
    m = PATH_RE.match(path.split("?", 1)[0])
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}", int(m.group(3))


def url(repo, number):
    return f"https://github.com/{repo}/issues/{number}"


def name_for(repo, number):
    """The conversation's name: the repo's short name and the ticket number."""
    return f"{repo.split('/')[1]}-{number}"


def is_map(labels):
    return MAP_LABEL in (labels or [])


def prompt(repo, number, info):
    """The first message of a new conversation for this ticket.

    A map opens wayfinder on itself, which then picks the next ticket. A
    ticket on a map opens wayfinder on its map with this ticket named. Any
    other ticket is simply handed over.
    """
    if is_map(info.get("labels")):
        return f"{WAYFINDER} {url(repo, number)}"
    parent = info.get("parent")
    if parent and is_map(parent.get("labels")):
        return f"{WAYFINDER} {url(repo, parent['number'])} {url(repo, number)}"
    return f"Read {url(repo, number)} and work on it."


def decide(sid, live, has_transcript):
    """What a click does: "reopen" an existing conversation (jump or resume),
    or start a "new" one. A conversation that never got as far as writing a
    transcript is as good as none."""
    if sid and (live or has_transcript):
        return "reopen"
    return "new"


# ------------------------------------------------------------------ state

def state_file():
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "agentview" / "tickets.json"


def load():
    try:
        got = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def remember(repo, number, sid):
    """Bind a ticket to its conversation, atomically."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    data[f"{repo}#{number}"] = sid
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def session_of(repo, number):
    return load().get(f"{repo}#{number}")


def new_session_id():
    return str(uuid.uuid4())


def command(sid, text):
    """argv for a new conversation with a fixed id, so the next click finds it."""
    return ["claude", "--session-id", sid, text]


# ------------------------------------------------------------------ GitHub

def _gh(path):
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def fetch(repo, number):
    """What the page and the prompt need, or {"error": ...} when GitHub does
    not answer. The parent and the blockers are optional: a failure there
    leaves them out rather than failing the page."""
    issue = _gh(f"repos/{repo}/issues/{number}")
    if not isinstance(issue, dict) or "title" not in issue:
        return {"error": f"GitHub did not return {repo}#{number}"}
    info = {"title": issue["title"], "state": issue.get("state", ""),
            "labels": [lb["name"] for lb in issue.get("labels", [])]}
    parent = _gh(f"repos/{repo}/issues/{number}/parent")
    if isinstance(parent, dict) and "number" in parent:
        info["parent"] = {"number": parent["number"], "title": parent.get("title", ""),
                          "labels": [lb["name"] for lb in parent.get("labels", [])]}
    blockers = _gh(f"repos/{repo}/issues/{number}/dependencies/blocked_by")
    if isinstance(blockers, list):
        info["blocked_by"] = [{"number": b["number"], "title": b.get("title", "")}
                              for b in blockers if b.get("state") == "open"]
    return info


# ------------------------------------------------------------------ page

def page(repo, number, info, status):
    """The confirmation page. `status` is "running", "closed" or "none"."""
    e = html.escape
    if "error" in info:
        body = f"<p class=warn>{e(info['error'])}</p>"
    else:
        rows = [f"<h1>{e(info['title'])}</h1>",
                f"<p class=meta><a href='{e(url(repo, number))}'>{e(repo)}#{number}</a>"
                f" · {e(info['state'])}</p>"]
        parent = info.get("parent")
        if parent:
            rows.append(f"<p class=meta>Map: <a href='{e(url(repo, parent['number']))}'>"
                        f"{e(parent['title'])}</a></p>")
        for b in info.get("blocked_by", []):
            rows.append(f"<p class=warn>Blocked by <a href='/ticket/{e(repo)}/{b['number']}'>"
                        f"{e(b['title'])}</a>. Work that one first.</p>")
        label = {"running": "Go to its conversation", "closed": "Resume its conversation",
                 "none": "Start a conversation on it"}[status]
        if info.get("blocked_by") and status == "none":
            label = "Start anyway"
        rows.append(f"<button id=go>{e(label)}</button><p id=out class=meta></p>")
        body = "\n".join(rows)
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Ticket {number}</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--mute:#6e6e73;--warn:#b3261e;--acc:#0a66c2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1c1e;--fg:#f2f2f7;--mute:#a1a1a6;--warn:#ff8a80;--acc:#64a8ff}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 16px}}
h1{{font-size:1.4rem}} a{{color:var(--acc)}} .meta{{color:var(--mute)}} .warn{{color:var(--warn)}}
button{{font:inherit;padding:.6rem 1.2rem;border-radius:8px;border:0;background:var(--acc);color:#fff;cursor:pointer}}
</style></head><body>{body}
<script>
const go = document.getElementById('go');
if (go) go.onclick = async () => {{
  go.disabled = true;
  const out = document.getElementById('out');
  try {{
    const r = await fetch('/api/ticket', {{method: 'POST', headers: {{'X-Fleet': '1', 'Content-Type': 'application/json'}},
      body: JSON.stringify({{repo: {json.dumps(repo)}, number: {number}}})}});
    const d = r.ok ? await r.json() : {{ok: false, reason: await r.text()}};
    out.textContent = d.ok ? ({{jumped: 'Brought to the front.', opened: 'Resumed in a new tab.',
      opening: 'Already opening.', started: 'Started in a new tab.'}}[d.did] || 'Done.')
      : 'Failed: ' + (d.reason || 'unknown');
  }} catch (e) {{ out.textContent = 'Failed: ' + e; }}
  go.disabled = false;
}};
</script></body></html>"""
