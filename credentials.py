"""Does a text carry a credential?

A Paste that does goes into the login keyring instead of a file (`paste.py`),
and its title, which the page shows in the clear, is refused. The project had
no list of credential shapes of its own, so this is the list: the token shapes
people paste by accident, and a password or token written as an assignment.

Narrow on purpose. A Paste wrongly called secret cannot be made whenever the
keyring is down, so a pattern here has to be one that ordinary prose, commands
and ids do not produce. What this misses, a session says with `--secret`.
"""
import re

# Not preceded by a letter or digit: "task-force-..." and "desk-research-..." end in "sk-".
_LEAD = r"(?<![A-Za-z0-9])"

SHAPES = [
    # The digit is looked for within a bound: an unbounded look-ahead rescans the rest of the text at every "sk-".
    re.compile(_LEAD + r"sk-(?=[A-Za-z0-9_-]{0,200}\d)[A-Za-z0-9_-]{20,}"),    # OpenAI, Anthropic
    re.compile(_LEAD + r"gh[pousr]_[A-Za-z0-9]{30,}"),                       # GitHub tokens
    re.compile(_LEAD + r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(_LEAD + r"xox[abeoprs]-[A-Za-z0-9-]{10,}"),                   # Slack
    re.compile(_LEAD + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),         # AWS access key id
    re.compile(_LEAD + r"AIza[0-9A-Za-z_-]{35}"),                            # Google API key
    re.compile(_LEAD + r"eyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,2000}\.[A-Za-z0-9_-]{8,}"),   # JWT
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),    # PEM, OpenSSH, PGP
    re.compile(r"\b(?i:bearer)\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(_LEAD + r"tskey-[a-z]+-[A-Za-z0-9-]{10,}"),                    # Tailscale
    re.compile(_LEAD + r"ya29\.[A-Za-z0-9_-]{20,}"),                         # Google OAuth
    re.compile(_LEAD + r"GOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(_LEAD + r"(?:sk|rk)_live_[A-Za-z0-9]{16,}"),                  # Stripe
    re.compile(_LEAD + r"whsec_[A-Za-z0-9]{16,}"),
    re.compile(_LEAD + r"glpat-[A-Za-z0-9_-]{20,}"),                         # GitLab
    re.compile(_LEAD + r"hf_[A-Za-z0-9]{30,}"),                              # Hugging Face
    re.compile(_LEAD + r"npm_[A-Za-z0-9]{30,}"),
    re.compile(_LEAD + r"xapp-\d-[A-Za-z0-9-]{20,}"),                        # Slack app token
    re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    re.compile(_LEAD + r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),        # SendGrid
    re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{20,}"),
    re.compile(r"(?<!\S)-u[ \t]+[\w.@-]+:(?=[^\s]*[\d_!@#%^&*+=])[^\s$<{%]{6,}"),                     # curl -u user:password
    re.compile(r"--(?:password|passwd|token|secret|api-key)[ \t]+(?![-$<{/]|id=|src=)[^\s]{8,}"),
    re.compile(r"://[^\s:/@]+:[^\s@/$<{%]{4,}@"),                            # user:password@host
]

_ASSIGNED = re.compile(
    r"(?:password|passwd|passphrase|wachtwoord|paswoord|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
    # Only the endings a credential's name has: DB_PASSWORD, STRIPE_SECRET_KEY, tokens, token2.
    # Not "token_count" or "password_policy_version", which are settings, not secrets.
    r"s?(?:[_-]?(?:key|value|string|\d{1,3}))?[\"']?[ \t]*(:|=|\bis\b)[ \t]*([\"']?)"
    # A value that is only a variable (`$DB_PASSWORD`) is a placeholder; a `$` inside one is a character.
    r"(?!\$[A-Za-z_{(])([^\s\"'`,;<>{}()\[\]]{8,})",
    re.IGNORECASE)


def _assigned(text):
    for found in _ASSIGNED.finditer(text):
        sep, quote, value = found.groups()
        if not re.search(r"[A-Za-z]", value):
            continue
        if sep == "=" or quote:
            # Written the way a config line or a line of code is: a value of eight letters is a
            # password. Code reading one (`token=settings.value`) is taken for one too: that costs
            # a Paste its file when the keyring is up, a missed password costs far more.
            return True
        # `name: value` or `name is value` in a sentence: a short plain word ("expires") is prose,
        # and so is a link or a ratio ("12.5k/200k"). Letters with a digit or a symbol are a
        # credential, and so is a long unbroken run.
        if "://" in value or re.match(r"\d[\d.,]*[kKmM]?/\d", value):
            continue
        if sep == "is":
            # Said in a sentence: "base64-encoded" and "OAuth2-based" are words. A symbol, or
            # mixed case with a digit and no hyphen, is a password.
            if re.search(r"[_!@#%^&*+=]", value) or (
                    "-" not in value and re.search(r"\d", value) and re.search(r"[a-z]", value) and re.search(r"[A-Z]", value)):
                return True
        elif re.search(r"[\d_!@#%^&*+=]", value) or len(value) >= 16:
            return True
    return False


def looks_secret(text):
    if not isinstance(text, str):
        return False
    return any(shape.search(text) for shape in SHAPES) or _assigned(text)
