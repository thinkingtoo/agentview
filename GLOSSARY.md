# agentview

A local page that shows the person at the keyboard what every coding-agent session on this machine is doing, so they can find the one that needs them.

## Language

**Session**:
One running conversation with a coding agent (Claude Code or Codex) on this machine, interactive or a worker.
_Avoid_: agent, tab, pane

**Project**:
A piece of work as the person thinks of it (a client's website, an internal tool), which may span several folders, worktrees or repositories.
_Avoid_: folder, directory, repo (when the unit of work is meant)

**Boss**:
A session that dispatches work to other sessions and leads them.

**Worker**:
A session that a boss leads.

**Track**:
The line of work a boss leads, with its workers. When a session belongs to a track, the track is its project, whichever repositories the work touches.

**Project identity**:
The key a project is known by, namespaced by what it is (`track:x`, `repo:host/owner/name`, `client:…`, `folder:x`), so a track, a repository, a client folder and a folder that share a name are never one project.
_Avoid_: project name (the name is what the person calls it, and changes)

**Pin**:
A project the person keeps at the front of the overview. Pinned projects lead in the order they were pinned.
_Avoid_: favourite

**Move**:
Putting a session, or a whole track or repository, into a project by hand. Moving a track or a repository holds for the sessions it will have; moving one session lasts as long as that session.

**Merge**:
Putting everything of one project into another by hand, so that the first is gone. Its pin and its context line go with it; the other project keeps its own name.

**Context line**:
A short line under a project's name that reminds the person what the project is about.
_Avoid_: description, summary

**Project card**:
The top of a project's column: its name, what it is about (the context line), for a track its status and how many of its boxes are ticked, and its movement.
_Avoid_: header, title bar

**Working-on line**:
A short line under a session's name that says what job the session is on, not what it is doing this minute.
_Avoid_: subject, status line

**Session line**:
What a session writes about itself at the end of each turn: where the work stands, and what is left for the person.

**Overview**:
The main page: every running project, separated, with its sessions.
_Avoid_: dashboard, roster

**Stuck**:
A session that cannot move on without something changing, of a kind the overview can name.

**Needs you**:
A kind of stuck: the session cannot go on until the person answers, approves, or does something themselves, such as running a command, sending a mail or buying something. A dialog Claude Code raises itself counts when it says what it waits on; a menu the person opened does not.
_Avoid_: waiting, ready, your turn

**Limit**:
A kind of stuck: the usage limit was reached and the session's last word is that error, or a "Session paused" dialog is open on usage credits. It goes on by itself when the limit resets, or when the person tells it to.
_Avoid_: rate limit error, throttled

**Error**:
A kind of stuck: any other API or authentication error is the session's last word (overloaded, auth, server). It ends the way any Failure does.
_Avoid_: crash

**Failure**:
The API error that is a session's last word: a Limit if it is the usage limit, an Error for any other. It ends when the model is asked or says anything again; a slash command run locally, or a `!` shell line, does not end it.

**Hung**:
A kind of stuck: the session is busy and nothing shows it moving, for ten minutes (`hung_after_minutes`) counted from its last sign of life of any kind. Waiting on a subagent, a background job or a command using CPU is moving, not Hung, for the six hours such a wait counts and the ten minutes after; so is a session whose processes could not be read.
_Avoid_: frozen, stalled, the old `stuck` flag

**Header counts**:
The three numbers at the top of the overview: sessions that need you, other stuck (an Error, a Hung or a Limit), and moving. The roster counts them and each session is in at most one, stuck winning over moving. A click on a count lights up its sessions and shrinks the columns with none to their card; a second click clears it.
_Avoid_: alarms, busy

**Banner**:
A band across the top of the page for a condition of the whole machine, such as a full disk, rather than of one session. It comes from the roster's `banners` and nowhere else: a session or an error that talks about a full disk is not one.

**Jump**:
One click that puts the terminal showing a session in front of the person. A session at a terminal has its own pane; a background session has none, so the click opens a new tab attached to it.

**Attached**:
A background session that a `claude attach` already shows in some window. The jump then goes to that window, never to a second copy, because two windows would write one conversation.

**Finished**:
A session that has been idle for hours (`finished_after_minutes`, 120) with nothing left for the person and its handover read in the overview. It stays one click away, because finished sessions are often picked up again.
_Avoid_: dead, forgotten, closed

**Pill**:
A finished session as one line at the foot of its project's column: name and idle time, its working-on line on hover, a click jumps. Counted in nothing. Any sign of life makes it a tile again.
_Avoid_: badge, chip

**Flags**:
The roster's list of every session on the machine, routines and finished sessions included, one row each: `{key, id, name, flag, blocked}`. `flag` is the raw one the transcript gave (`waiting`, `ready`, `tool`, `stuck` or none) and `blocked` whether the session wrote down what blocks it. The chime and the server's marks read this list; the tiles may say less than it does. It replaced the roster's `blocks`.
_Avoid_: blocks

**Pin (a session)**:
Holding a finished session open as a full tile until it is unpinned or the session closes. Kept in agentview's own state, not in config. Not the pin on a project card, which puts the project first.

**Handover read**:
The person has seen what the session said when it stopped, as of that stop, in the overview: a jump that reached the terminal, or a click on a tile with none, which reads the stop that tile showed and no later one. Separate from the chime's seen mark, which the old block view also wrote and which a failed jump once wrote too; those old marks do not finish a session.

**Movement**:
Visible evidence that a session is still making progress, including while it waits on CI or tests.
_Avoid_: activity, liveness
