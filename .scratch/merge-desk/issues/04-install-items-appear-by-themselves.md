# 04: Install items appear by themselves, and a ticked Install installs

**What to build:** AgentView reads the `uv tool` receipts (`~/.local/share/uv/tools/*/uv-receipt.toml`); for each tool installed from a `sweatshop-ai/*` or `tiroir/*` git URL whose pinned rev is not its `main`, an Install item is on the desk (under its own heading). A ticked Install runs `uv tool install --reinstall --from git+<url>@<main sha> <package>` and the tool's restart (sheaf: `sheaf stop`, `sheaf start`), and writes the installed commit under the item.

**Blocked by:** 02, 03 (a ticked Install goes through the watcher 03 builds; boss, 2026-11-13)

**Claimed by:** Suki 2026-11-13 23:56

**Status:** done, on branch suki/04-install-items (not merged into dev; waits for Tarek's turn)

- [x] sheaf behind main shows one Install item with both commits; sheaf at main shows none (tests/test_deskinstall.py Scan.test_a_tool_behind_main_is_one_item_with_both_commits, test_a_tool_at_main_has_none; real receipt shape parsed in Receipts)
- [x] A failed install leaves the old install running and says the error under the item (uv 0.13.5 proved in a sandbox to keep the old tool on resolve and build failures; Press.test_a_failed_install_leaves_the_old_one_and_says_so_and_never_restarts)
- [x] The restart happens after the install succeeded, never before (Press order test; mutation 'restart before install' fails 3 tests)
