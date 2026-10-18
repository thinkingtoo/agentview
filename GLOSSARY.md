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

**Jump**:
One click that puts a session's own terminal in front of the person.

**Movement**:
Visible evidence that a session is still making progress, including while it waits on CI or tests.
_Avoid_: activity, liveness
