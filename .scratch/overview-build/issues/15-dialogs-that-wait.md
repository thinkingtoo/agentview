# 15: Dialogs that wait on the person

**What to build:** Claude Code writes the waiting word "dialog open" for a menu the person opened (07's ruling: not stuck), but also for dialogs the session raises itself and that wait on the person: "Session paused" (retry on a fallback model, edit the prompt, continue on usage credits, switch models), the classifier billing notice, the managed settings review, the ultraplan choice and the auto-mode default. Those carry a `needs:` text that the roster does not read today, so such a session reads "not stuck" while it waits on the person. Found by the Opus hunt on ticket 08 and checked against Claude Code 2.1.295 on 2026-10-19. A "dialog open" with a `needs:` text is Needs you, with that text as the reason; "Session paused" for usage is Limit. A menu the person opened, with no `needs:` text, stays not stuck.

**Blocked by:** 08

**Claimed by:** Bettina 2026-10-19 20:21

**Status:** in-progress

- [ ] The roster classifies "dialog open" with and without a `needs:` text, tested on invented registry rows: a person-opened menu (not stuck), a session pause for usage (Limit), a billing notice and a settings review (Needs you with the reason)
- [ ] Counts from the agentview event log and the session registry: how many "dialog open" openings carry a `needs:` text, per kind; counts and kinds only
- [ ] The chime flags are unchanged where no `needs:` text is present (differential against origin/dev)
- [ ] The `needs:` text renders as text (R7) and holds no transcript text (R6)
