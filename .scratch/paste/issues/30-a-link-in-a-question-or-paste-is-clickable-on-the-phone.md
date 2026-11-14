# 30: A link in a question or a Paste can be tapped on the phone

**What to fix:** on the phone, a URL inside a concierge question or a Paste is plain text: the person cannot tap it, and copying a long URL on a phone is slow. Render `http(s)://…` in question text and in a Paste's text as a link (opening in a new tab), escaped like the rest of the text.

**Seen:** 2026-11-14 01:10, merge-desk (boss Tarek): Thierry on his phone, asked to open the merge desk at https://…:8445/desk, answered "I need a clickable link"; the link had to go out through Slack instead.

- [ ] A URL in a question's text is a tappable link on the card (phone and laptop)
- [ ] A URL in a non-secret Paste is a tappable link
- [ ] Text that only looks like a URL inside a word is not linked; no HTML from the text is ever rendered

**Blocked by:** None.

**Status:** needs-triage
