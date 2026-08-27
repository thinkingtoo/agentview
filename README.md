# claude-fleet

A local page showing what every Claude Code session on this machine is working
on, grouped by project.

![fleet](docs/screenshot.jpg)

It generates nothing. Claude Code already writes everything the page shows:

| What | Where it comes from |
|---|---|
| Who is running, and how busy | `~/.claude/sessions/*.json` — the peer files |
| What the session is about | the `ai-title` record in its transcript — Claude's own title, rewritten as it learns |
| What it was last asked | the `last-prompt` record |
| Which branch | `gitBranch` on the transcript's user records |

Names come from [claude-agent-names](https://github.com/sweatshop-ai/cc-agent-names),
but nothing here requires it — an unnamed session shows whatever Claude Code
called it.

## Run it

```bash
python3 server.py          # http://127.0.0.1:8765
```

Or as a service that survives reboot:

```bash
cp claude-fleet.service ~/.config/systemd/user/
systemctl --user enable --now claude-fleet
```

Bound to `127.0.0.1` deliberately: the page shows your prompts verbatim, which
is client work and occasionally a credential someone pasted into an error.

## Shelves — how a project gets its name

The hard part is that a working directory is not a project name.

`~/Projects/clients/harbor` is the **harbor** project, but its
git root is `clients` — which would collapse every client into one block.
Its basename works, until `~/Projects/clients/acme/site` shows
up as `tiroir` and collides with the unrelated site project.

So `config.json` declares which directories are **shelves**: places that hold
projects without being one.

```json
{ "shelves": ["~", "~/Projects", "~/Projects/clients"] }
```

A project is the first directory below the deepest shelf containing the cwd.
Anything deeper becomes a breadcrumb, which is exactly the client/project
distinction: **acme › site**. A session sitting *on* a shelf has no project
and lands in the `No project` block at the bottom — that block is where ad-hoc
work and unattended routines live, and it is not hidden.

Add a shelf whenever a directory starts holding projects instead of being one.

## Tests

```bash
python3 -m unittest discover -s tests
```

They cover the two things worth covering: project resolution (including the
`acme › site` and on-a-shelf cases) and reading the summary records out of
a transcript, including a headless session that has no title at all.
