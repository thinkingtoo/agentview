"""A stand-in for ~/.claude/routines/branch_deploys.py, so the desk tests do not read what this machine has.

It mirrors the classifier's OUTPUT (what the desk parses), not its YAML reading:
  <file name>                      one per workflow that fires on a push to <branch>, or does not parse
    <n>: <line>                    a hint: any line of the file, but a comment, that mentions deploy, publish, upload or secrets
    (no deploy, ...)              when there is none
    = structure sha256:<32 hex>    the keys and their indent, not their values (--full)
    ! could not parse: <why>      a tab indent or a bracket that never closes
  exit 1 and no output when nothing fires and nothing fails to parse.
It reads only the shapes the desk tests write: `on: push`, `on:` + `push:` + `branches: [a, b]`, one key per line.

Run as `stub_classifier.py <repo-dir> <branch> [--full]`; `use()` points deskships at it.
"""
import hashlib
import re
import sys
from pathlib import Path

HINT = re.compile(r"deploy|publish|upload|secrets", re.I)
TRIM = " \t"
NONE = "  (no deploy, publish, upload or secret line found: reads as tests only)"


def _unparsed(text):
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("\t"):
            return f"ScannerError at line {n}"
    if sum(text.count(c) for c in "[{") != sum(text.count(c) for c in "]}"):
        return f"ParserError at line {len(text.splitlines())}"
    return ""


def _fires(text, branch):
    lines = text.splitlines()
    on = next((i for i, l in enumerate(lines) if re.match(r"on:", l)), None)
    if on is None:
        return False
    if re.match(r"on:\s*(push|\[.*\bpush\b.*\])\s*$", lines[on]):
        return True
    block = []
    for l in lines[on + 1:]:
        if l.strip() and not l.startswith(" "):
            break
        block.append(l)
    for i, l in enumerate(block):
        if re.match(r"  push:", l):
            for m in block[i + 1:]:
                if re.match(r"  \S", m):
                    break
                if (found := re.match(r"\s+branches:\s*\[(.*)\]", m)):
                    return branch in [b.strip() for b in found.group(1).split(",")]
            return True
    return False


def _structure(text):
    keys = [f"{len(l) - len(l.lstrip(' '))}:{re.sub(r'^- ', '', l.strip()).split(':')[0]}" for l in text.splitlines()
            if l.strip() and not l.strip().startswith("#")]
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:32]


def classify(root, branch):
    out = []
    for path in sorted((Path(root) / ".github" / "workflows").iterdir()):
        text = path.read_text(encoding="utf-8")
        if why := _unparsed(text):
            out += [path.name, f"  ! could not parse: {why}"]
        elif _fires(text, branch):
            hints = [f"  {n}: {l.strip(TRIM)}" for n, l in enumerate(text.splitlines(), 1)
                     if HINT.search(l) and not l.lstrip().startswith("#")]      # only spaces and tabs are trimmed: a no-break space stays
            out += [path.name] + (hints or [NONE]) + [f"  = structure sha256:{_structure(text)}"]
    return out


_saved = []


def use():
    """Point deskships at this stub (setUpModule); `restore()` puts the real path back (tearDownModule)."""
    import deskships
    _saved.append(deskships.CLASSIFIER)
    deskships.CLASSIFIER = Path(__file__).resolve()


def restore():
    import deskships
    deskships.CLASSIFIER = _saved.pop()


if __name__ == "__main__":
    if not (Path(sys.argv[1]) / ".git" / "HEAD").is_file():
        sys.exit("not a checkout")
    lines = classify(sys.argv[1], sys.argv[2])
    if lines:
        print("\n".join(lines))
    sys.exit(0 if lines else 1)
