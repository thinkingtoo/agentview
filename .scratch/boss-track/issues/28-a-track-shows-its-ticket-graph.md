# 28: A track shows its ticket graph

**Status:** needs-triage

**Why (2026-11-19, Thierry):** He asked whether boss tracks should all move to GitHub issues so the
graph and the status could be followed visually. The tickets stay in local markdown (`.scratch/<track>/issues/`,
his choice in an AskUserQuestion). The visual view comes here instead.

**What exists:** the track card shows the goal's Done when rows with their tickets' states
(`objectives.py`, ticket 01), and the goal opens as a sheaf page (`goal_page.py`). Nothing shows the
graph itself: which ticket waits on which, which are ready, claimed, done.

**What to build:** from the goal's `## Tickets` source, the output of
`frontier.py --json <issues-dir>` (claude-boss `skills/hand-to-boss/frontier.py`) drawn as a graph:
one node per ticket with its number, title and state (ready, claimed by a worker, waiting, done),
one edge per Blocked by, an external blocker shown with who holds it. Reached from the track card.
A `gh:owner/repo#N` source (one track: `avetta-address-book`) uses the same JSON.

Open for triage: a page of agentview's own, or a mermaid block rendered by sheaf next to the goal page.

- [ ] A track card links to its graph; the graph shows every ticket of the source with its state
- [ ] An edge per Blocked by; a ticket blocked by something outside the source shows it as external
- [ ] The graph is read from `frontier.py --json`, never from a second parser of the ticket files
