"""One-shot runs started by a session, folded into that session's tile.

A `codex exec` run lasts a minute or two and there are many of them (most of
the rollouts on a busy machine). A tile each would flood the page, so a run is shown where
it matters: as movement inside the tile of the session that started it,
"waiting on: codex review, 2 min". A provider tells what a run is (`run`, a
label), which processes are above it (`ancestors`, nearest first) and which
background task of its starter holds it, if one does (`task`; see `base.py`);
this looks for a session of any provider among the processes. A run whose
starter is not on the page -- not found, not running, a routine, which has no
tile -- is left to be a tile of its own, marked exec.

Two rollouts held by one process are one run: `codex exec review` writes one
for the run and one for its review. And the run's writes go where the run goes,
into its starter's, so they are counted once.
"""

SLOTS = 30


def pid_of(raw):
    pid = raw.get("pid")
    return pid if isinstance(pid, int) and pid > 1 else None


def is_run(raw):
    return isinstance(raw, dict) and isinstance(raw.get("run"), str) and bool(raw["run"].strip())


def strip_of(raw):
    """A provider's strip if it is one: 30 counts, each a whole number or None."""
    value = raw.get("writes")
    if (isinstance(value, list) and len(value) == SLOTS
            and all(v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0) for v in value)):
        return value
    return None


def added(strips):
    """Strips summed minute by minute; a minute any of them did not see is unknown."""
    strips = [s for s in strips if s is not None]
    if not strips:
        return None
    return [None if any(s[i] is None for s in strips) else sum(s[i] for s in strips) for i in range(SLOTS)]


def task_of(raw):
    """The id of the starter's background task that holds the run, if the run says."""
    task = raw.get("task")
    return task if isinstance(task, str) and task.strip() else None


def ancestors_of(raw):
    above = raw.get("ancestors")
    return [p for p in above if isinstance(p, int) and p > 1] if isinstance(above, list) else []


def one_run(group):
    """The run that a process's rollouts make: the exec one to stand for it, a
    review if any of them is, the earliest start, and every rollout's writes."""
    stands = next((r for r in group if r.get("kind") == "exec"), group[0])
    starts = [r["startedAt"] for r in group
              if isinstance(r.get("startedAt"), (int, float)) and not isinstance(r.get("startedAt"), bool)
              and r["startedAt"] > 0]
    label = "codex review" if any(r["run"] == "codex review" for r in group) else stands["run"]
    return dict(stands, run=label, startedAt=min(starts) if starts else 0,
                writes=added([strip_of(r) for r in group]))


def fold(pairs, now):
    """The `(provider, raw)` pairs the roster shows: runs folded into their starters."""
    owners = {}
    for index, (_, raw) in enumerate(pairs):
        if (isinstance(raw, dict) and not is_run(raw) and pid_of(raw)
                and isinstance(raw.get("id"), str) and raw["id"]
                and not (isinstance(raw.get("routine"), str) and raw["routine"])):
            owners.setdefault(pid_of(raw), index)
    groups = {}
    for index, (_, raw) in enumerate(pairs):
        if is_run(raw):
            groups.setdefault(pid_of(raw) or ("raw", id(raw)), []).append((index, raw))
    out, amended = list(pairs), {}
    for members in groups.values():
        run = one_run([raw for _, raw in members])
        starter = next((owners[p] for p in ancestors_of(run) if p in owners), None)
        for index, _ in members[1:]:
            out[index] = None
        first = members[0][0]
        if starter is None:
            out[first] = (out[first][0], run)
            continue
        out[first] = None
        provider, raw = amended.get(starter) or (out[starter][0], dict(out[starter][1]))
        since = max(0.0, (now * 1000 - run["startedAt"]) / 60000) if run["startedAt"] else 0.0
        jobs = list(raw["bgTasks"]) if isinstance(raw.get("bgTasks"), list) else []
        # A run under one of the starter's own background tasks is that task, which
        # the starter already lists: a second job would count the one shell twice.
        held = task_of(run)
        if held is None or not any(isinstance(job, dict) and job.get("id") == held for job in jobs):
            raw["bgTasks"] = jobs + [{"label": run["run"], "since": since}]
        if strip_of(raw) is not None and run["writes"] is not None:
            raw["writes"] = added([strip_of(raw), run["writes"]])
        amended[starter] = out[starter] = (provider, raw)
    return [pair for pair in out if pair is not None]
