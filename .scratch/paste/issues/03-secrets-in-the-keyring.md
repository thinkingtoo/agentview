# 03: Secrets in the keyring

**What to build:** a Paste with a password, token or API key never sits in a plain file. The session can mark it secret, and text matching the secret patterns the project already redacts with is treated the same way even when it was not marked. Its text goes into the person's login keyring (freedesktop Secret Service); the store keeps only a reference. The page shows it as dots with a working copy button; done or withdraw deletes the keyring item. When the keyring cannot be reached, the command refuses: there is no plain-file fallback. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** 01 (One Paste end to end).

**Status:** ready-for-agent

- [ ] A Paste marked secret lands in the keyring and nowhere in the store directory (checked by scanning the directory's bytes)
- [ ] An unmarked text containing a token is detected and handled as secret
- [ ] The page shows a secret as dots; opening it does not unmask it; copy copies the real text
- [ ] Done and withdraw delete the keyring item
- [ ] An unreachable keyring makes the command exit non-zero and leaves nothing on disk
- [ ] The roster never carries a secret's text, not even the first line
- [ ] Tests use a fake keyring that records calls; no test touches the real keyring
