# Claude Team

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
cp claude-team.service ~/.config/systemd/user/
systemctl --user enable --now claude-team
```

Bound to `127.0.0.1` deliberately: the page shows your prompts verbatim, which
is client work and occasionally a credential someone pasted into an error.

## Speed

Transcripts are big — 58 MB across ten sessions here, one of them 27 MB — and
the busy ones change every few seconds. Reading them whole on every poll cost
**~9 seconds a round**, which is what made clicking feel broken: the click was
fine, the server was busy re-reading megabytes.

So a transcript is read **once, from its tail**, and after that only the bytes
appended since. A partial final line is left for next time; a file that shrank
or whose opening bytes changed is read again from scratch. Cold **14.4s →
0.84s**, warm **0.28s → 0.03s**.

A jump asks WezTerm and tmux first and only enumerates Konsole over D-Bus if
neither claimed the session, and validates the pid from the peer files alone
rather than building the whole page. The click is also acknowledged before the
request goes out — raising a terminal takes the focus off the page, and a
browser throttles a page it is not showing, so feedback that waits for the
response is feedback you never see.

## Click a card, get the terminal

Clicking a session raises the terminal it is running in. The page never guesses
how — the server resolves the route per session, because they are not alike:

| Host | How it is asked | Matched by |
|---|---|---|
| WezTerm | `wezterm cli activate-pane` | the session's pty against `tty_name` in `wezterm cli list` |
| tmux | `select-window` + `select-pane`, **then** whatever hosts the attached client | the `tmux` field in the peer file, then the client's tty |
| Konsole | `Window.setCurrentSession` over D-Bus | `Session.processId()` against the session's ancestry |

Then `wmctrl` raises the window. A session inside tmux inside WezTerm needs two
of these in the right order — selecting the tmux pane achieves nothing while the
WezTerm tab stays hidden.

Sessions Claude Code spawned itself have a pty but no window, and are not
clickable. They are also the ones that **survive closing their view** — a
background worker belongs to the daemon, not to a terminal, so exiting detaches
you without stopping it. The uptime is what gives that away.

**Requires X11.** Window raising uses `wmctrl`; under Wayland a client cannot
raise another client's window, and the in-emulator half would still work while
the window stayed where it was. Also needs whichever of `wezterm`, `tmux` and
`qdbus` you actually use — each route is skipped if its tool is missing.

## Arranging it yourself

The order is recomputed every few seconds: whichever project has someone
**busy** leads, ties broken by most recent activity, and `No project` always
sits at the bottom.

That is right until it isn't — the two or three projects you check every day
should be where you left them, not where today's activity puts them. So:

- **Drag a block** to place it. Everything down to where you dropped it becomes
  **pinned** and stops moving; the rest keeps sorting itself underneath.
- **Click the ✳** on a pinned block to let it go again.
- **Click a project name** to rename it. The name you type is a label —
  the real key underneath does not change, so a rename never orphans its pin.
- **Click the line under a session** to write your own. It replaces
  Claude's generated title *and retitles that terminal tab*, so the page and
  the tab never disagree.

Clicking anywhere *else* in a session still raises its terminal — the two
never overlap, because a terminal arriving in front steals the focus and would
close the field you are typing in.

All of it lands in `config.json`, so it survives restarts and you can edit it
by hand.

**An override on a session dies with the session.** It is keyed by `sessionId`,
which is gone once you close that Claude. A project rename is keyed by the
project and lives forever.

## Routines keep to themselves

A systemd timer firing `claude -p` is a session like any other, and there are
six of them here — `nightly-report` every 20 minutes, `gpu-watch`
every 10, and the daily ones. They run from `~`, which is no project, so they
used to land in **No project**: the pile that means *assign me*, which is the
one thing a routine never needs.

So they get a block of their own, at the very bottom — below `No project`,
because that pile is asking you for something and a routine is asking for
nothing. Each row is badged with the routine that started it, and the block
takes no pin, no rename and no drop.

Two signals are needed to call one, and both must agree. The peer file says
`entrypoint: sdk-cli` where a terminal says `cli` — that only proves it is
headless. The *name* comes from the script above it in the process tree,
`~/.claude/routines/nightly-report.sh` → `nightly-report`. `claude -p` typed by
hand is headless too, and calling that a routine would be a guess.

**Nothing has to clean them up.** A run lasts three or four minutes — twenty
when a transcription is in flight — and the page lists a session only while
its pid answers, so the card goes on its own the moment the run ends.

## Finding one

Type in the box (or press **`/`**) to filter. It matches a project's name, a
session's name, its title, its last prompt, the branch and the path — from
**three characters** on, because fewer than that matches nearly everything and
only makes the page flicker while you type.

Sessions needing you are counted across *everyone*, not just what survived the
filter: a filter must never hide something that is stuck.

Each session also shows **how long it has been up**. A background worker two
days old reads very differently from a tab opened a minute ago — and it is the
usual explanation for a session that will not go away.

## Stuck and waiting

Two different problems, so two different marks — the row is tinted, its dot
beats, the tab title carries a count, and the project it belongs to rises.

| Mark | What it means | Where it comes from |
|---|---|---|
| **waiting** (amber) | Blocked on something outside itself | status `waiting`, after a short grace |
| **stuck Nm** (red) | It thinks it is working and it is not | `busy`, transcript silent, **and nothing running** |
| **tool Nm** (grey) | A tool call has been going a very long time | a `tool_use` with no `tool_result` yet |

**`waiting` does not always mean waiting for *you*.** Often it does — a
permission prompt, a question. But a session that runs `/btw` also sits in
`waiting` while the helper it spawned answers, and nobody needs to do anything.
So the label says `waiting` and no more than that; `"waiting_after_seconds": 20`
keeps the two-second flickers out.

**A running tool call is not a stuck session.** The transcript is silent for the
whole of a tool call, so silence alone proves nothing — a session six minutes
into `timeout 580 ...` looks exactly like a hung one from outside. What tells
them apart is a `tool_use` with no `tool_result` answering it yet. Only when
that has been outstanding absurdly long is it worth mentioning, and then it is
news, not an alarm: no tint, no beat, just a grey badge.

The transcript's mtime is the heartbeat here, and it has to be: `updatedAt` in
the peer file **does not move while a session works** — a session busy for ten
minutes looks identical to one hung for ten minutes if you only read that.

**A background session may show its own title as its name.** Claude Code names
a `bg` session a moment after starting it, and until then its name is the
conversation title — which is why a `/btw` helper can appear twice over. The
page prints the title once when the two are identical, and the real name
arrives on the next refresh.

**Idle is never stuck.** A session idle for two days is finished or abandoned;
flashing it forever would only teach you to ignore the flashing.

`"stuck_after_minutes": 5` sets how long silence with nothing running is
allowed; `"long_tool_minutes": 20` sets when a running tool call is worth
mentioning.

## Size

`config.json` carries the page's own scale:

```json
{ "zoom": 1.5 }
```

Set it there rather than zooming in the browser, and keep the browser itself at
100% — the two multiply, and 150% twice over is 225%, which drops the grid to a
single column. The value is substituted server-side, so the page never renders
at the wrong size first and then jumps.

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

`tests/ui_smoke.py` is separate: it drives the real page with Playwright
against a running server — rename, line override, drag-to-pin, unpin — and is
not part of `unittest discover`. Run it with `python3 tests/ui_smoke.py`.

The unit tests cover the three things worth covering: route selection for each terminal
(including tmux-inside-WezTerm and a headless session with nowhere to go),
project resolution (including the
`acme › site` and on-a-shelf cases) and reading the summary records out of
a transcript, including a headless session that has no title at all.
