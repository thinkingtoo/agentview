# 04: Install items appear by themselves, and a ticked Install installs

**What to build:** AgentView reads the `uv tool` receipts (`~/.local/share/uv/tools/*/uv-receipt.toml`); for each tool installed from a `sweatshop-ai/*` or `tiroir/*` git URL whose pinned rev is not its `main`, an Install item is on the desk (under its own heading). A ticked Install runs `uv tool install --reinstall --from git+<url>@<main sha> <package>` and the tool's restart (sheaf: `sheaf stop`, `sheaf start`), and writes the installed commit under the item.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] sheaf behind main shows one Install item with both commits; sheaf at main shows none
- [ ] A failed install leaves the old install running and says the error under the item
- [ ] The restart happens after the install succeeded, never before
