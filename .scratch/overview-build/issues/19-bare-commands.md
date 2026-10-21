# 19: A command written with no quote and no `$`

**What to build:** a copy button for a command a session writes bare in its ask (`Run the wizard: bash ~/stage/wizard.sh`, `unlock the key (ssh-add ~/.ssh/id_maple)`), without ever offering prose. The owner chose on 2026-10-21 "yes, when the evidence is strong". On the real asks of 2026-10-17..21 this would add 4 of the 19 buttons ticket 18 reached with it.

**Blocked by:** 18

**Status:** needs-triage

## What ticket 18 learned (three Opus hunts, inputs in the session scratchpad, not kept)

The rule tried in `81d0893` (`ask_commands.py`, `bare_commands`): after a colon to the end of the ask, or alone in brackets; a known program with a sign; no letters-only word among the arguments unless the tool's subcommand; no `?`, `!` or comma clause; the colon only after a run verb with no negation. Each hunt found prose it took for a command:

1. A `?`/`!` or a comma clause pasted with the command; one prose word taken as an argument (`rm -rf ~/maple adesso`); `Done: rm -rf ...`; `$(...)` read as a bracket.
2. A prose word inside (`git pull in ~/maple`, `rm -rf ~/build or ~/dist`); `cd ..` cut to `cd .`; report labels a list never ends (`Errore:`, `Executed:`, `Don't run:`).
3. A run verb as a noun or in a report (`Run failed: npm run build --prod`, `Start date:`, `I tried to run:`); a verb in an earlier comma clause; `Don’t` with U+2019; prose stuck to punctuation (`~/build / ~/dist`, `& ~/dist`, `e.g.`); the bracket path with no verb or negation check (`Never run this (git push --force) without asking me`); `(as root)` dropped; placeholders `<branch>`; quadratic time over many colons (67 ms at 400 characters).

A start, from hunt 3: the verb at the start of its clause and imperative (optionally after please/now/then), nothing but an object between it and the colon; brackets only after such a verb too; any shell metacharacter or punctuation-only word outside quotes refuses; one pass over the colons, not one scan per colon.

An alternative that needs no guessing: the hook already asks for the quotes or the `$ `. Most bare commands came before that sentence existed (2026-10-20). Measure how many bare commands sessions still write under the current hook before building this.
