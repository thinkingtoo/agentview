# Which movement and stuck signals can Codex sessions give?

Type: research
Status: open
Blocked by: none

## Question

Using "What signals show that a session is moving?" and "Which kinds of stuck does the overview name, and how is each detected?": for a Codex session on this machine, which of these can agentview read, and from where: transcript or rollout writes per minute (for the project strip), a shell under it using CPU, background work, an open question or approval prompt (Needs you), a rate limit or API error as the last record (Limit, Error), and the busy/idle state that Hung needs? Codex has no session-line hook, so it never has `did`, `ask` or `n`. Facts only: file paths, record types and field names from the Codex version installed here, never conversation text.
