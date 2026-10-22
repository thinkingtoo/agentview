# 03: Secrets in the keyring

**What to build:** a Paste with a password, token or API key never sits in a plain file. The session can mark it secret, and text matching the secret patterns the project already redacts with is treated the same way even when it was not marked. Its text goes into the person's login keyring (freedesktop Secret Service); the store keeps only a reference. The page shows it as dots with a working copy button; done or withdraw deletes the keyring item. When the keyring cannot be reached, the command refuses: there is no plain-file fallback. Spec: `docs/specs/2026-10-21-paste.md`.

**Blocked by:** 01 (One Paste end to end).

**Claimed by:** Habib 2026-10-21 23:27

**Status:** done

- [x] A Paste marked secret lands in the keyring and nowhere in the store directory (checked by scanning the directory's bytes) (`Secrets.test_a_marked_secret_goes_to_the_keyring_and_nowhere_in_the_store` scans every byte; live: `grep -r` of the store dir for the dummy value found nothing, merged bd6620b)
- [x] An unmarked text containing a token is detected and handled as secret (`test_an_unmarked_text_with_a_token_is_handled_as_a_secret`, `tests/test_credentials.py`)
- [x] The page shows a secret as dots; opening it does not unmask it; copy copies the real text (`ui_smoke.paste_pass` green on the rebased head: dots, opening does not unmask and fetches nothing, copy puts the real text; live: text route returned the value, 403 without `X-Fleet`)
- [x] Done and withdraw delete the keyring item (`test_done_deletes_the_keyring_item_and_the_record`, `test_withdraw_deletes...`, the gone-session meeting test; live: withdraw with `--provider claude` left `vault.ids` empty and the roster count back to 0)
- [x] An unreachable keyring makes the command exit non-zero and leaves nothing on disk (`test_a_keyring_that_cannot_be_reached_makes_the_command_fail_and_write_nothing`, real-subprocess variant with a dead bus)
- [x] The roster never carries a secret's text, not even the first line (`test_the_roster_never_carries_a_secrets_text...`; live: roster showed `first: ""`, `secret: true`, no value anywhere in the JSON)
- [x] Tests use a fake keyring that records calls; no test touches the real keyring (`FakeVault`; no test touches the real keyring; suite on t-compute at ec58707: 2233 tests OK, 4 skipped; review `reviews/paste-03-codex-6.md` GO at ec58707, Opus fallback)
