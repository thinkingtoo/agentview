# Merge desk: the sheaf page where finished work waits for Thierry to merge, deploy or install

The merge desk is the part of AgentView that keeps every pull request and every local install that only the person can release, and shows them on one sheaf page with a button per item. It exists because on 2026-11-13 fourteen reviewed sheaf PRs and 105 merged but uninstalled commits were found by chance: the queue needed a live boss to reach the person, and nothing closed the gap between merged and installed. Settled in a grilling with Thierry on 2026-11-13 (session Kenji); the first draft is `~/.claude/plans/merge-desk.md`.

## What the merge desk holds

One list of items, each waiting only for the person's hand. An item is one of three kinds:

| Kind | What the press does | Where items come from |
|---|---|---|
| Merge | merges the PR into its base, only at the commit that was reviewed | a session hands it over (`desk ready`), or the daily scan finds it |
| Deploy | the same merge, on a repo where the merge ships something; the item shows what ships first | as Merge; v1 repos: `tiroir/apex` (Deploy workflow), `tiroir/telemasterclass` (Cloudflare Pages) |
| Install | reinstalls a locally installed tool from its `main` and restarts what runs it | AgentView itself: every `uv tool` installed from a `sweatshop-ai/*` or `tiroir/*` git URL whose installed commit is not `main`'s (sheaf today) |

Each item carries: repo, PR number or tool, the pinned commit, one line on what it does, the recommendation (merge, wait, don't) with its evidence (reviews, CI), the order it must go in (`after: 262`), and the session that handed it over.

**Who writes the line and the recommendation.** The session that hands the item over, since it holds the reviews. AgentView adds only what it reads itself: CI state, mergeability, how long the item has waited. An item found by the daily scan says "found, no recommendation yet".

**Not in v1:** the tiroir boxes (tiroir-tt and the others), whose changes go through stages Thierry approves, not CI; tiroir-central, decommissioned 2026-10-21.

## The page

The desk is a sheaf page, and the only view of the list (Thierry: the sheaf page is the view; AgentView gets a button that opens it).

- One fixed file, `~/.local/state/agentview/merge-desk.md`, rendered by the laptop's sheaf hub. AgentView edits it one item at a time, never the whole file, so the person's comments stay on the items they are about; an item that leaves takes its thread with it.
- Each item is one list item whose first line carries its button, then the evidence on the indented lines below:

  ```markdown
  - [ ] Merge sweatshop-ai/sheaf#272: the dictation time limit covers the whole call
    - Recommendation: merge. Opus GO, Codex one P2 (follow-up), CI green on ead9a1f.
    - Handed over by Faisal, 2026-11-13 10:40; waiting 11 h.
  ```

  A list, not a table, because Markdown has no box in a table cell. Tables with buttons are a wanted sheaf feature (sheaf `.scratch/action-buttons/issues/05`), and the desk moves to them when sheaf has them.
- A comment with Tell on an item goes to the session that handed it over, through sheaf's own Tell.
- Install items sit under their own heading at the end; Deploy items carry a "What ships" sub-list: the workflows that fire and their deploy lines (`~/.claude/routines/branch_deploys.py`) and the commits that go out.

## A press and what follows

The page uses sheaf's own action buttons: `Merge`, `Deploy` and `Install` join sheaf's fixed list of one-off action words (sheaf ticket 04), drawn as a button on their own line (sheaf ticket 01). A press writes `[x]` into the file, as every sheaf action does; sheaf calls nothing outside itself.

AgentView watches the file. For each newly ticked item, one at a time, in the order of the page:

1. **Pinned commit.** The PR's head must still be the pinned commit; anything pushed since gives "not merged: the branch changed after the review".
2. **GitHub's re-check.** While GitHub answers `UNKNOWN` (it recomputes every open PR after a merge), wait up to 60 s, asking every 2 s.
3. **Mergeable.** Anything but `MERGEABLE` is "not merged: GitHub says <state>".
4. **Merge** with a merge commit and `--match-head-commit <pinned>`.
5. **The result goes under the item**, as a sub-line: `Merged as 41678e3 at 21:35` or `Not merged: …`. A refused press unticks the box, so it can be pressed again once fixed. A merged item leaves the page at the next day's tidy, not at once, so the person sees what happened.

An Install press runs `uv tool install --reinstall --from git+<url>@<main sha> <package>`, then the tool's restart (`sheaf stop`, `sheaf start` for sheaf), and writes the installed commit under the item.

Every press and its result also go to a log, `~/.local/state/agentview/merge-desk.log`, one line each, readable by sessions (`desk status`).

## Reaching it

- **AgentView** gets a header button "Merges" with the number of items waiting, like the Pastes button: it lights none of the three header counts, and a click opens the desk page.
- **The ring:** once a day at most, when the oldest item has waited more than 24 hours, AgentView rings as for a session that needs the person, and the ring names the desk.
- **The phone:** the page opens from the FleetView link in Open WebUI's rail on thinkingtoo.tiroir.me, through AgentView's tailnet address (`tailscale serve`, `:8445`). The laptop's sheaf hub answers only on 127.0.0.1, so AgentView relays the desk page and its `/_/` routes for the tailnet origin (the relay ticket 03 of the chat box used for the iPhone test is the model). Presses from the phone work like presses on the laptop (Thierry: buttons work from the phone too).
- When the laptop is off, nothing is merged; that is accepted (the GitHub login stays on the laptop).

## How sessions hand work over

A command beside `paste` in `hooks/`:

```sh
desk ready sweatshop-ai/sheaf 272 --what "the dictation time limit covers the whole call" \
  --rec merge --why "Opus GO, CI green on ead9a1f" [--after 262]
desk status [sweatshop-ai/sheaf 272]     # waiting, merged as <sha>, or refused and why
desk withdraw sweatshop-ai/sheaf 272
```

`desk ready` pins the PR's current head. Handing over the same PR again replaces the item and re-pins. This replaces "ask the person through the concierge with a Paste" for merges; bosses and concierges are told so in the claude-boss plugin (ticket 09).

## The daily scan

Once a day AgentView lists the open PRs of the repos it knows (those of its projects) that are green, mergeable and older than a day, and adds those no session handed over, as "found, no recommendation yet". It also tidies: merged and withdrawn items older than a day leave the page.

## Names

In AgentView, **Merge** now means a pull request going into its base branch, GitHub's word (Thierry, 2026-11-13). Putting one project into another, called Merge until now, becomes **Fold into** (ticket 01).
