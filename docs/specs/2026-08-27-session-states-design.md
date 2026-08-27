# What a session's dot should mean

**Status:** approved design, not yet built · 2026-08-27

## The problem

The page paints Claude Code's status verbatim, and Claude Code has four:

| status | when Claude Code sets it | page today |
|---|---|---|
| `busy` | `isLoading \|\| delegatedActive` — the model is working | green dot |
| `waiting` | a dialog is open, **with a `waitingFor` string** | amber dot |
| `idle` | everything else | grey dot |
| `shell` | idle, **with a background shell job still running** | amber dot |

`idle` is the whole problem: it means *"finished, your turn"* and *"abandoned
since Tuesday"* with the same grey dot. Nothing on the page says a session has
something ready for you, which is the one thing you actually want to be told.

Two facts from the live log, which is where this design came from:

```
23:22:38  status      Elke   busy -> waiting
23:22:38  waitingFor  Elke   None -> "input needed"
23:23:26  status      Elke   waiting -> busy
```

`waitingFor` is Claude Code's own words for what a session is blocked on, and
the page throws it away. And `shell` turns out to be common — one session
crossed `busy -> shell -> busy` eleven times in an hour, which is what a
session running background jobs between turns looks like.

## The design

### 1. One field, five states

`fleet.py` stops exporting `stuck` (which would now have to hold the value
`ready`) and exports `flag`:

| flag | rule | mark | motion |
|---|---|---|---|
| `stuck` | busy, transcript silent, nothing running *(unchanged)* | red dot | slight pulse, 1.8s |
| `waiting` | status `waiting`, once it is real (below) | amber dot | slight pulse, 2.2s |
| `ready` | `idle`, not seen since it went idle | **blue ✓** | still |
| `tool` | a tool call outstanding very long *(unchanged)* | grey badge | still |
| *none* | busy, or idle and already seen | green / grey dot | busy breathes, 3.6s |

Precedence: `stuck` → `waiting` → `ready` → `tool`.

**`shell` counts as idle**, so it can be ready. The name misleads: the binary
computes it as `status === "idle" && <something about this session's tasks>`,
and Claude Code's own taxonomy calls a background `local_bash` task a "shell"
(as against an `agent` or a `monitor`). So it is *the model has stopped, but a
background job it started is still running* — not *the user is at a shell*. The
turn is over either way, which is what ready is about; the running job earns a
small `bg` badge, not a different state.

### 2. Ready is keyed to the moment it stopped

`~/.local/state/claude-team/seen.json`, `{sessionId: statusUpdatedAt}` — machine
state, deliberately not `config.json`, which is yours to hand-edit.

> ready ⇔ `status == "idle"` and `seen[sessionId] != statusUpdatedAt`

A session that works again and stops again carries a new `statusUpdatedAt`, so
it comes back as ready by itself: no clearing pass, nothing to go stale.
Answering in the terminal rather than on the page sends it `busy` and then
`idle` again, which is correctly a *new* thing to read.

Clicking a card marks it seen, whether or not the jump lands — a jump that
fails is still you looking.

### 3. The highlight follows the words, not a stopwatch

The tinted row with the bar down its edge is the thing that reads as "this one
wants you", so it should arrive when the want does:

- `waitingFor` present → the row highlights **immediately** and prints those
  words (`input needed`, `sandbox request`, or the dialog's own label).
- amber with nothing named → fall back to the existing
  `waiting_after_seconds: 20` grace, which exists because a `/btw` helper sits
  in `waiting` for a few seconds and the tint would flash on and off.

### 4. The hint is Claude's last words

The incremental transcript scan already reads the tail; it now also keeps the
last assistant text block, trimmed to one sentence (≤140 chars).

- **Skip `isSidechain` records** — a subagent must never speak for the session.
- **Skip tool-only turns** — the quote is always something addressed to you.
- On a ready row the quote **replaces the last-prompt line**: the prompt is
  what you said, the quote is what it said back, and the newer one wins. Row
  height does not change.
- On a waiting row, `waitingFor` shows as a badge beside the flag instead.

### 5. Motion means working

The current 1.55× beat is what reads as an alarm; it goes.

- **busy** — dot breathes slowly (3.6s, scale 1 → 1.18, opacity 1 → .65) and a
  soft grey highlight travels through the name (4.5s, low contrast).
- **waiting / stuck** — a slight pulse only (2.2s / 1.8s, scale 1 → 1.12). The
  tint and the badge are what distinguish them.
- **ready** — perfectly still. A blue ✓ in the dot's slot.

### 6. Where ready ranks

- Within a block: `waiting`/`stuck` → `ready` → `busy` → recency. A ready
  session therefore becomes the one shown open when its project is folded.
- Between blocks: ready outranks busy, below stuck.
- The header counts it (`2 ready`, in accent blue).
- **The tab title does not.** That count is an alarm and a finished session is
  not one — otherwise the tab reads `(5)` all evening.

## Deliberately not doing

- Guessing whether a turn "asked a question" from its punctuation. My turns end
  in statements that still need a decision; the quote says more than the guess.
- Any per-session state in `config.json`.
- A "mark all seen" button until there is a day where the list is long enough
  to want one.

## Testing

Units: the flag rules including `shell` never being ready and the `waitingFor`
shortcut; the seen store round-trip and its re-arming on a new
`statusUpdatedAt`; last-said extraction (sidechain skipped, tool-only turn
skipped, long message trimmed, no assistant text at all).

Smoke: only busy animates; ready is a still blue ✓; a waiting row with
`waitingFor` highlights on the first poll; clicking a ready card marks it seen
and it stays seen across polls.
