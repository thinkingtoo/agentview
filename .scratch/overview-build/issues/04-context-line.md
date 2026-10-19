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

**Real-data check (2026-10-19, counts only):** 33 goal files, 25 repositories of the roster and 54 repository columns from every checkout under the projects folder, read through the real roster: 0 lines with raw markdown syntax, 0 lines empty where a prose source exists. Hunt 5 ran a wider corpus (5,054 README and instruction files, node_modules included) and found 7 shapes that corpus holds and this one did not; they are being fixed.
