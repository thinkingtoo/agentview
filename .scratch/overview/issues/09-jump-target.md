# Where does one click land, for each kind of stuck?

Type: grilling
Status: resolved
Blocked by: none

## Question

Using "Which kinds of stuck does the overview name, and how is each detected?": for Needs you (question, permission prompt, things left on the session line), Limit, Error and Hung, where does the jump land: the terminal pane, its tab, the open dialog, the line's words? What happens when no terminal is attached to the session, or the session runs in the background? Today's jump (`jump.py`) covers part of this; what does it miss?

## Answer

Resolved 2026-10-18 by grilling, in two rounds. Jump log since 2026-09-22: 403 jumps, 395 worked, 8 failed (6 "no terminal hosts this session", 2 "wezterm cli spawn failed", from 3 sessions, each clicked 2 to 4 times in a row). 14 opened a new tab to attach an unattached tmux session. On 2026-10-18, all 20 live sessions could be jumped to.

- **One target for every kind.** Needs you, Limit, Error and Hung all land on the session's terminal pane, as `jump.py` does today. An open question or permission prompt is drawn in the pane itself. What differs per kind lives on the page as its context: the question, the reset time, the error type, the last tool.
- **Several things left (`n` > 1)**: the pane. The list is in the session's last message, at the bottom of the pane, and the row reads "3 things left for you".
- **The stuck session itself**, never its boss. A boss that relays the question shows Needs you on its own row.
- **Background sessions** (`claude --bg`) open in a new tab with `claude attach <id>`, the same way an unattached tmux session does today. This is what `jump.py` misses now.
- **No terminal, or a failed jump**: worked out before the click. The row shows "no terminal", greyed, instead of the jump. A failed jump leaves its reason on the row until the next poll. The page never opens a second copy of a running session.
