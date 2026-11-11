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

**Claimed by:** Nia 2026-11-11

**Status:** done

## Answer (Nia, 2026-11-11)

`goalLinkOf` (`index.html`) asks `onTheHub(g.url)`: the url parses (`new URL`), its protocol is `http:` and its `hostname` is `127.0.0.1`. A url that does not parse links nothing. The href is still `g.url` as sent, through `esc()`.

### Evidence

- **Test** (`tests/test_goal_href.py`, `test_a_url_whose_host_is_not_127_0_0_1_or_that_does_not_parse_is_not_linked`): `http://127.0.0.1:x@evil.example/p.md`, `http://127.0.0.1:7417@evil.example/p.md`, `http://127.0.0.1:7417.evil.example/p.md` and `http://127.0.0.1:[/p.md` each give one `<span>` "no goal page". `_page_js()` now also takes `onTheHub` out of the page.
- **Red** before the fix (4 failures, one per url), e.g. `AssertionError: Lists differ: ['a'] != ['span']` with `'href': 'http://127.0.0.1:7417.evil.example/p.md'`.
- **Green:** `test_goal_href` 2 OK (run here: t-compute has no `node`, and the test skips without it; laptop load 11.8). The first test (a quote or markup in a 127.0.0.1 url stays in the href) still passes, so a real hub url still links.
