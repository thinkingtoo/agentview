# 04: Context line and track status

**What to build:** Each project card reminds the person what the project is about. Context line, first that exists: the person's own line (edited in place, stored in `project_lines`), a track's goal Outcome first sentence, a repository's README first prose paragraph then the opening of its agent instructions, otherwise up to two recent session titles greyed as a guess with "add a line". Cut at about 140 characters, full text on hover. Tracks show their status tag and "N of M" (MET shows done). Default names are prettified slugs with the raw slug on hover. A notes link searches the brain on click.

**Blocked by:** 02

**Claimed by:** Hugo 2026-10-19 08:31

**Status:** in-progress

- [ ] Each source is chosen in order and the person's own line always wins
- [ ] A MET track shows done whatever its boxes say
- [ ] No project has no context line
- [ ] The notes link queries only on click; tests never carry brain text

**Known limit:** a goal's first sentence ends at the first full stop before a capital letter or a digit, so an abbreviation ("Dr. Rossi", "Oct. 15") cuts it short; the hover has the whole paragraph (ruling 3, hunt 4).

**Real-data check (2026-10-19, counts only):** the owner's corpus, read through the real roster: 33 goal files and 55 repository columns (48 with a README or agent instructions, 7 with neither): 0 lines of raw markdown syntax, 0 lines empty where a prose source exists. The one `<..>` the script flags is a literal `user:<id>` the owner wrote inside a goal sentence, shown as written (decided). Corpus pass (evidence, not a gate; every README, AGENTS.md and CLAUDE.md on the disk, `find / -xdev`, one per sha256): 9,064 files, 0 exceptions, slowest 11 ms. Lines that still hold raw syntax on the card: 734 before the hunt-5 fixes, 679 after (hover text 934 and 878); empty results 198 and 139. What remains is third-party fidelity (shortcut `[ref]` links, `<slug>` placeholders, `#word`, rst and txt READMEs), kept under NOTES by ruling. Hunts: 5 found 7 (fixed), 6 found 2 hangs (fixed), 7 found 1 hang, a file of 33,334 one-character paragraphs (fixed: a file's first 300 paragraphs are looked at; the first prose of 8,926 real files sits at most at the 102nd).
