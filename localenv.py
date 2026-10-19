"""The `NAME=value` files of the person's own configuration, which hold keys
and so stay out of this public repo: `~/.config/tiroir/agentview-*.env`."""


def read_env(path):
    """The settings in an env file as a dict. Blank lines and `#` comments are
    skipped, and a value may be quoted."""
    got = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            got[name.strip()] = value.strip().strip("'\"")
    return got
