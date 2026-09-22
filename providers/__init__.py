"""The providers built into the repo. Imported by the core, not discovered.

Entry points and a path list in `config.json` are for after the contract has
held up two real providers; that is written down in the design, not here.
"""
import importlib

BUILT_IN = (("claude", "ClaudeProvider"), ("codex", "CodexProvider"))

_all = None
_broken = {}


def all():
    """One instance per provider, kept for the life of the process: they
    carry the caches that make a poll cheap. A provider whose module does
    not even import is left out and reported by `broken()` -- one bad
    provider must not take the page down."""
    global _all
    if _all is None:
        found = []
        for module, cls in BUILT_IN:
            try:
                found.append(getattr(importlib.import_module(f"providers.{module}"), cls)())
            except Exception as exc:              # its own bug, its own badge
                _broken[module] = f"{type(exc).__name__}: {exc}"[:200]
        _all = found
    return _all


def broken():
    all()
    return dict(_broken)
