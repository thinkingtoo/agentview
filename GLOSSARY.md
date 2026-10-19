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

**Context line**:
A short line under a project's name that reminds the person what the project is about.
_Avoid_: description, summary

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
A kind of stuck: the session cannot go on until the person answers, approves, or does something themselves, such as running a command, sending a mail or buying something.
_Avoid_: waiting, ready, your turn

**Limit**:
A kind of stuck: the usage limit was reached and the session's last word is that error. It goes on by itself when the limit resets, or when the person tells it to.
_Avoid_: rate limit error, throttled

**Error**:
A kind of stuck: any other API or authentication error is the session's last word (overloaded, auth, server). A new prompt or any other word from the session ends it.
_Avoid_: crash

**Failure**:
The API error that is a session's last word: a Limit if it is the usage limit, an Error for any other. It ends when the model is asked or says anything again; a slash command run locally, or a `!` shell line, does not end it.

**Hung**:
A kind of stuck: the session is busy and nothing shows it moving, for ten minutes (`hung_after_minutes`) counted from its last sign of life of any kind. Waiting on a subagent, a background job or a command using CPU is moving, not Hung, for the six hours such a wait counts and the ten minutes after; so is a session whose processes could not be read.
_Avoid_: frozen, stalled, the old `stuck` flag

**Jump**:
One click that puts the terminal showing a session in front of the person. A session at a terminal has its own pane; a background session has none, so the click opens a new tab attached to it.

**Attached**:
A background session that a `claude attach` already shows in some window. The jump then goes to that window, never to a second copy, because two windows would write one conversation.

**Finished**:
A session that has been idle for hours with nothing left for the person and its handover read. It stays one click away, because finished sessions are often picked up again.
_Avoid_: dead, forgotten, closed

**Movement**:
Visible evidence that a session is still making progress, including while it waits on CI or tests.
_Avoid_: activity, liveness
