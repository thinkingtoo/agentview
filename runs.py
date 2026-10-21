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
from providers import base, minutes


def pid_of(raw):
    pid = raw.get("pid")
    return pid if isinstance(pid, int) and pid > 1 else None


def is_run(raw):
    return isinstance(raw, dict) and isinstance(raw.get("run"), str) and bool(raw["run"].strip())


def strip_of(raw):
    """A provider's strip if it is one."""
    return raw["writes"] if minutes.is_strip(raw.get("writes")) else None


def task_of(raw):
    """The id of the starter's background task that holds the run, if the run says."""
    task = raw.get("task")
    return task if isinstance(task, str) and task.strip() else None


def ancestors_of(raw):
    above = raw.get("ancestors")
    return [p for p in above if isinstance(p, int) and p > 1] if isinstance(above, list) else []


def start_of(raw):
    """When the run began, in milliseconds, or None when the row names no such time:
    a number past what a clock holds would stop the whole roster at its first sum."""
    return base.milliseconds(raw.get("startedAt"))


def one_run(group):
    """The run that a process's rollouts make. The oldest rollout stands for it (it
    is the run's own; the others are what the run started), the newest says what
    the run is doing now, the run began when the first did, and every rollout's
    writes are the run's. Rollouts that do not say when they began are taken in
    the order given."""
    dated = [r for r in group if start_of(r) is not None]
    stands = min(dated, key=start_of) if dated else group[0]
    latest = max(reversed(dated), key=start_of) if dated else group[-1]
    return dict(stands, run=latest["run"], startedAt=min(map(start_of, dated)) if dated else 0,
                writes=minutes.added([strip_of(r) for r in group]))


def owns(raw):
    """Can a run be folded into this row: a session with a process, that is no run and no routine?"""
    return (isinstance(raw, dict) and not is_run(raw) and bool(pid_of(raw))
            and isinstance(raw.get("id"), str) and bool(raw["id"])
            and not (isinstance(raw.get("routine"), str) and raw["routine"]))


def fold(pairs, now):
    """The `(provider, raw)` pairs the roster shows: runs folded into their starters."""
    # The roster shows one row for a `provider:id` -- the first, or a later one that leads
    # a track when the first does not -- so that is where a run under any of its pids goes.
    # If that row cannot own a run (a routine, or no process), the run goes nowhere: it is
    # a tile of its own, not movement in a row the roster drops.
    kept = {}
    for index, (provider, raw) in enumerate(pairs):
        if isinstance(raw, dict) and isinstance(raw.get("id"), str) and raw["id"]:
            first = kept.setdefault((provider.name, raw["id"]), index)
            if bool(raw.get("boss")) and not bool(pairs[first][1].get("boss")):
                kept[(provider.name, raw["id"])] = index
    owners = {}
    for index, (provider, raw) in enumerate(pairs):
        if owns(raw):
            stays = kept[(provider.name, raw["id"])]
            if owns(pairs[stays][1]):
                owners.setdefault(pid_of(raw), stays)
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
        # The run is marked as one: a Codex run works, so it is movement even
        # when the session that started it has ended its turn (ticket 20).
        held = task_of(run)
        if held is None or not any(isinstance(job, dict) and job.get("id") == held for job in jobs):
            raw["bgTasks"] = jobs + [{"label": run["run"], "since": since, "run": True}]
        else:
            raw["bgTasks"] = [{**job, "run": True} if isinstance(job, dict) and job.get("id") == held
                              else job for job in jobs]
        if strip_of(raw) is not None and run["writes"] is not None:
            raw["writes"] = minutes.added([strip_of(raw), run["writes"]])
        amended[starter] = out[starter] = (provider, raw)
    return [pair for pair in out if pair is not None]
