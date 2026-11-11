# 33: The goal link's guard checks a prefix, not the host

**What to fix:** `goalLinkOf` links any url that starts with `http://127.0.0.1:`. `http://127.0.0.1:x@evil.example/p.md` passes, and its host is `evil.example` (`127.0.0.1:x` is userinfo). Check `new URL(g.url).hostname === "127.0.0.1"`, and pin it in `tests/test_goal_href.py` (which pins only `esc()`).

**Input:** `track.goal.url = "http://127.0.0.1:x@evil.example/p.md"`. The server cannot send this today: the port is an `int` and each segment goes through `quote(safe="")` (`goal_page.py`).

**Failing line:** `index.html:856`:

```js
  if (typeof g.url !== "string" || !g.url.startsWith("http://127.0.0.1:"))
```

**Class:** c (latent).

**Found in:** Follow-up bug hunt over the track's merged PRs (Kwame, Opus fallback, 2026-11-11), verified at 17386f1.

**Blocked by:** None.

**Status:** needs-triage
