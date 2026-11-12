# 35: A command that ends in `|`, `&&` or `>` is offered whole

**What to fix:** `cut_or_broken` (`ask_commands.py`) never rejects a trailing shell mark, so a command cut after its mark gets a copy button: `$ ls -la |` offers `ls -la |`, `$ git status &&` offers `git status &&`, `$ ssh maple-box 'df -h' |` offers `ssh maple-box 'df -h' |`. Pasted, the shell waits for more. Half a command is worse than none.

Also unpinned (same hunt, finding 2): with ticket 29's C1 fix, `holds_a_command` is the only guard against a quoted name or port after a plain word followed by a mark (`$ ssh to 'maple-box' | tee x`, `$ ssh on '2222'; then` offer nothing, correctly); no test has a shell mark after such a quote.

**Found in:** Codex review 1 of PR #28 (Opus fallback, run by Nia, 2026-11-11), findings 1 and 2, VERIFIED at 4edcf3a. The trailing-mark gap is on 0f8f7e9 for every command; PR 28 lets plain ssh hosts back into it, as before ticket 27.

**Class:** c.

**Blocked by:** None.

**Claimed by:** Stellan 2026-11-12

**Status:** done

## Fix and evidence (Stellan, 2026-11-12)

`cut_or_broken` rejects a command that ends in an open mark (`OPEN_MARK`): `|`, `||`, `|&`, `&&`, a redirect (`>`, `2>`, `&>`, `>&`, `<`, `<<`) or a backslash continuation; an escaped `\|` is spared. Finding 2 is pinned by `test_a_shell_mark_after_a_quoted_name_offers_nothing`.

- **Red:** `test_a_command_that_ends_in_a_shell_mark_is_not_offered`, 6 subtests failed (`$ ls -la |` offered `ls -la |` and so on), on `Stellan/ask_commands.py`.
- **Green:** `tests/test_guessed_commands.py` 158 OK (`test_guessed_commands` + `test_ask`).
- **Real asks** (`measure-19-dump.py`, every distinct `team-line --n 1` ask in `~/.claude/projects`, dump in `/dev/shm`, deleted after): 3476 asks; origin/dev 198 buttons, this branch 198, 0 asks differ. The fix loses no real button.
