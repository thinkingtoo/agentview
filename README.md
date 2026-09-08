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
| Where it left things, and what it wants | the session itself, asked as it stops (see below) |
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

## What a session says about itself

The two lines under a name answer two questions: **what is this**, and **where
is it now**. Claude Code writes neither. Its `ai-title` is written once and
rarely revisited — of thirteen title lines on this page one morning, five said
nothing about the work (three empty, one `clear-conversation`, one the name of
a slash command) and a sixth described a Dutch 404 while the session was
deploying something else. The second line was worse: a finished session printed
the *last line* of its last message, which is a sign-off as often as an ask, and
a working session printed **your own last prompt back at you**.

So the session is asked. A Stop hook (`hooks/stop_line.py`) gives it two fields
as it finishes:

| Field | What it is |
|---|---|
| `did` | Where the work stands. One sentence, in the language of the conversation. It **replaces** the `ai-title` line, which becomes its fallback. |
| `ask` | The one thing it is blocked on, in its own words. |
| `n` | How many things it needs from you before it can go further. `0` when it can carry on without you. |

**Words when there is one, a count when there are more.** A single blocked
question is short enough to answer from the page. Four of them are a trip to the
terminal, and quoting the first of four misrepresents the size of the job — so
the card says `4 answers needed`. It reads as a pair:

```
Design settled through Q16, nothing written yet.
4 answers needed
```

**`n: 0` is the important half.** A card that wants nothing renders one line and
stays short, so the taller cards are the ones asking. That is the alarm, done
with height rather than colour.

**The hook asks only when it has to.** If the session is already ending on a
question, `ask_from()` reads it straight out of the transcript and the hook
writes that line itself, silently. Paying an extra model turn to rewrite a line
that is already right is the wrong half of the cost. Only when nothing readable
is there does it block, and `stop_hook_active` — Claude Code's guard against a
hook holding a session open forever — makes sure it blocks once and no more.
Claude Code also *discards* a Stop-hook block on turns that end without
re-invoking the model, so a line will occasionally be missing; extraction is the
fallback, and it is deliberately conservative.

**A read ask fills the words and does not raise the count.** Extraction can see
a question. It cannot tell one that stops the session from one that offers to do
more, and a tab that says `(6)` has to mean six. Only a session that wrote `n`
itself joins `waiting` and `stuck` in the header and the tab title, and leads
its block.

**While it works, the line is the call in flight** — *Editing fleet.py*,
*Reading 3 files*, or, for a Bash call, the description the caller already
wrote. Between calls it falls back to the session's own running commentary. An
MCP tool is addressed `mcp__<server>__<tool>`, which is a wire address; the page
says *Gmail users drafts create*.

**A need dies when the work resumes.** The prompt that restarted a session is
the answer to what it asked, so the line is dropped the moment the session goes
busy. A stale need is worse than none: it makes the page lie at the next stop.

The lines live in `~/.local/state/claude-team/lines/`, beside `seen.json` and
out of `config.json` — that file is yours to hand-edit, this one is rewritten by
a hook. Sessions that are gone are forgotten on the next poll.

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

- **`auto-arrange`** in the header stops the shuffling altogether. Held, the
  content still updates — status, titles, flags — and only the positions
  freeze, so a card cannot walk out from under the sentence you are reading.
  Anything that arrives while it is held joins the end rather than pushing into
  the middle. It replaced a Refresh button, which solved nothing: the page
  polls anyway. *Held* is remembered in `config.json`, but the order it froze
  is not — so a reload adopts whatever it paints first and holds **that**.
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

## A boss and its team

A session that invokes the `boss` skill (`~/.claude/skills/boss/`) coordinates other
sessions and does no implementation work itself. On the page it **leads its
project block** whatever the activity, carries a `boss` badge, and names the
team it dispatches to; that team renders indented beneath it, so the block has
the shape of the team instead of being a flat list of eight equals. A worker
whose boss sits in another block cannot be nested there, so it says `↳ Lennart`
in words instead.

**A worker's `ready` stays folded.** It keeps the blue tick, so the boss's
block shows at a glance which of his team have reported back, but it does not
open a card: that ✓ is his to act on, not yours. `waiting` and `stuck` still
open on a worker — a permission prompt is answered by you, whoever dispatched
the work.

Both facts come from the transcript and neither is a guess:

- **Boss**: the skill being *started*, in either of the two ways that happens
  — the model calling the `Skill` tool with `{"skill": "boss"}`, or you typing
  `/boss`, which Claude Code writes as a `<command-name>` line in a plain-text
  user record. They look nothing alike on disk, and matching only the first
  missed a second boss for a morning. A session that merely *reads* the
  skill's files (which is how this feature got written) carries every one of
  those words in a tool result, and is not marked.
- **Team**: the `to` of every `SendMessage` that session has made, liveliest
  correspondent first, minus anyone no longer running and minus other bosses —
  two bosses exchanging a message is not a chain of command.

A skill can be started well into a session: `/boss` was typed a third of the
way into a 1.8 MB transcript. So a bounded head scan is not enough; the file
is read once, in full, guarded by a substring pass over the raw bytes so only
a transcript that mentions the skill at all is ever parsed.

The message graph alone would not do: workers message **each other** as much as
they message the boss, so the hub of the graph is not the boss. Only the
invocation says who is running the team.

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

## What the mark in front of a name means

Claude Code writes four statuses — `busy`, `waiting`, `idle`, `shell` — and
`idle` is the whole problem: it means *finished, your turn* and *abandoned on
Tuesday* with the same grey dot. So the page works out one flag per session:

| Mark | What it means | Where it comes from |
|---|---|---|
| **blue ✓ ready** | It finished, and you have not looked since | `idle`, and not seen since it stopped |
| **amber waiting** | Something on screen is asking | status `waiting` — at once if it names what it wants |
| **red stuck Nm** | It thinks it is working and it is not | `busy`, transcript silent, **and nothing running** |
| **grey tool Nm** | A tool call has been going a very long time | an unanswered `tool_use` that is still the newest thing said |
| **green, breathing** | Working | `busy` |

**Ready is keyed to the moment it stopped**, not to the session
(`~/.local/state/claude-team/seen.json`). A session that works again and stops
again carries a new `statusUpdatedAt`, so it comes back as ready by itself —
nothing has to be cleared and nothing can go stale. Clicking a card marks it
seen, whether or not the jump lands. A ready row prints **the last thing the
session said to you** rather than the last thing you said to it: on a finished
session, the newer of the two is the handover — unless the session wrote its
own line, which is better than either.

**`waiting` does not always mean waiting for *you*.** Claude Code writes a
`waitingFor` string — `input needed`, `sandbox request`, the dialog's own
label — whenever something is really on screen, and the page prints it. A
`/btw` helper sits in `waiting` for a few seconds and names nothing, so an
unnamed wait still serves `"waiting_after_seconds": 20` before it is flagged.

**`shell` is not what it sounds like.** It is `idle` with a background job the
session started still running — Claude Code's own taxonomy calls a background
`local_bash` task a *shell*. The turn is over, so it can be ready; the running
job earns a small `bg` badge and nothing more.

**Motion means working, and only working.** The busy dot breathes slowly and a
soft highlight travels through the name. Waiting and stuck nudge, barely — the
colour is the alarm; anything stronger is a thing you learn to stop seeing. A
still page means nothing is running.

**The page has two sounds, and they are the same bell.**

- **A session that starts waiting rings**: two strokes, high then low, with a
  long decay — the cabin chime when the seatbelt sign comes on, not a
  doorbell.
- **A session that finishes ticks**: one stroke, gone in a third of a second.
  Something arrived, and it is not asking you for anything.

Either sounds **once**, for whoever has just started waiting or finishing:
never for the ones already on screen when you open the page, and never again
while that same session sits there. Five landing in one poll is one sound, not
five, and when a question and a finished turn arrive together you hear the
question. `chime` in the header turns both off (it says *muted* then), and the
setting lives in `config.json` with the pins.

A browser makes no sound at all until you have interacted with the page, so
the first click anywhere arms it. If a chime is due before that has happened,
the button turns red and says **allow sound** — clicking it is both the
gesture the browser wanted and the switch.

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

## Filling the columns

Blocks are packed, not flowed: each one is measured at the width it will have
and handed to whichever column is currently shortest. A CSS grid gave every
block in a row the height of the tallest one in it; CSS columns balanced by
their own rules and left slack that a block could not break into. Packing
keeps the bottom edges roughly level, and a project that appears while you are
watching lands in the gap rather than at the foot of the last column.

The DOM order is therefore a layout detail, not the order you read — so
dragging a block to pin it works off the painted order the page kept, never
off `querySelectorAll`.

A project is the first directory below the deepest shelf containing the cwd.
Anything deeper becomes a breadcrumb, which is exactly the client/project
distinction: **acme › site**. A session sitting *on* a shelf has no project
and lands in the `No project` block near the bottom — ad-hoc work, and it is
not hidden. Routines sit lower still, in a block of their own.

Add a shelf whenever a directory starts holding projects instead of being one.

## When something looks wrong

Nothing on this page is generated, so when it says something strange the
answer is usually in what it read, or in what a click actually ran. Both are
written down:

```bash
python3 log.py            # the last 60 events
python3 log.py -f         # follow
python3 log.py -k error -k slow
python3 log.py -w Vera    # everything mentioning one session
```

`~/.local/state/claude-team/events.jsonl`, one JSON object per line, rotated
at 5 MB. It records four things, and each one is there because it is what you
go looking for:

| Kind | Why it is kept |
|---|---|
| `session.seen` / `session.gone` / `status` / `waitingFor` | Sampled from the peer files every two seconds by a thread of its own, so the history exists whether or not a browser was open. A routine that ran for four minutes at 03:00 left no trace at all before this. |
| `action` / `retitle` / `jumped` | Every POST, with what it asked for and what actually ran on the terminal. A tab that ends up called something surprising can be traced to the click that did it — which is how two tabs came to be called `RIGA`. |
| `error` / `page.error` | Exceptions, including JavaScript ones, which used to be invisible: the poll stops, the page goes quietly stale, and nothing anywhere says why. Repeats are collapsed — the first one is the news, the next four hundred are noise. |
| `slow` | An operation over its budget, and **no line at all** when it was fast. The 9-second poll that made clicking feel broken would have written a line a round. |

Silence is the normal state of the file.

## Tests

```bash
python3 -m unittest discover -s tests
```

`tests/ui_smoke.py` is separate: it drives the real page with Playwright
against a running server — rename, line override, drag-to-pin, unpin, folding,
the routines block — and is not part of `unittest discover`. Run it with
`python3 tests/ui_smoke.py`. It puts back everything it touched, **including
the tab titles it renamed**: an override does not only live in `config.json`.

The unit tests cover the things worth covering: route selection for each
terminal (including tmux-inside-WezTerm and a headless session with nowhere to
go), project resolution (including the `acme › site` and on-a-shelf
cases), reading the summary records out of a transcript, telling a routine
from a hand-run `claude -p`, a boss from a session that has merely read the
skill, and the log — that a heartbeat alone says nothing, that a repeated
error is written once, and that a fast operation writes no line at all.

**Every test points at the code the page actually calls.** There used to be a
second, full-file scanner that nothing called, and the summary tests ran
against *that* — so they stayed green while the live one carried a badge bug
for the whole of its life. If a test can only be written against a function
the page does not use, the function is the problem.
