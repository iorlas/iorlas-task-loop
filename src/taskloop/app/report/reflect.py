"""`tl reflect digest`: turn the engine's per-run reflections into fixes (tl-bl5).

The loop calls maybe_run() on every pass: once a day, a detached `tl reflect digest`. The digest reads the `reflection` of every run
in traces.jsonl (all repos), clusters them (domain/report/reflect.py) and for each cause that recurs files one bead in the repo that
owns the cause (engine and prompt: task-loop; delegate: delegate; the rest: the project the runs ran in). A cause already filed (the
state file, or an open bead of that repo with a like title) gets a comment with its new runs instead; one whose bead is closed and that
happens again gets a new bead that names the old one. State: ~/.config/task-loop/reflect-digest.json."""

import json
import os
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools, childenv, ident, landlock
from taskloop.contracts import wire
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, NewBead, Spawner
from taskloop.contracts.snapshots import ReflectState
from taskloop.contracts.stores import ReflectStateStore, ReposStore
from taskloop.domain.report import matchers
from taskloop.domain.report.reflect import (
    OWNERS,
    TITLE_SIMILAR,
    acceptance,
    cluster,
    description,
    evidence_lines,
    is_recurring,
    items_of,
    jaccard,
    same_cause,
    tokens,
)

DAY = 86400


def state_store() -> ReflectStateStore:
    return ReflectStateStore(ConfigDir(ident.config_dir()))


def read_state() -> dict[str, Any]:
    """The digest's state as a plain dict the digest edits (fields at their defaults when there is no file; Refused when the file is torn or
    of another version: the memory of what was filed is never read as empty, or every cluster would be filed again)."""
    return (state_store().need() or ReflectState()).to_dict()


def write_state(st: dict[str, Any]) -> None:
    state_store().write(wire.load(ReflectState, {"v": ReflectState.V, **st}))


def items(since: float, until: float, traces: str | Path | None = None) -> list[dict[str, Any]]:
    """The went_badly items of the reflected runs ended in the window, oldest first."""
    path = traces or ident.config_dir() / "traces.jsonl"
    rows: list[Any] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for ln in lines:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    return items_of(rows, since, until)


def registered() -> list[str]:
    return [p for p in ReposStore(ConfigDir(ident.config_dir())).known() if (Path(p) / ".beads").is_dir()]


def resolve_repo(value: object, repos: Sequence[str]) -> str:
    """A trace's `repo` is the origin's URL (or the worktree path when there is no origin): -> the registered repo folder it is."""
    v = str(value or "")
    if not v:
        return ""
    if v in repos:
        return v
    if os.path.isdir(v):
        real = os.path.realpath(v)
        hits = [p for p in repos if real == os.path.realpath(p) or real.startswith(os.path.realpath(p) + os.sep)]
        return max(hits, key=len) if hits else ""
    name = matchers.repo_name(v)
    for p in repos:
        if Path(p).name == name:
            return p
    return ""


def owner_repo(c: dict[str, Any], repos: Sequence[str] | None = None) -> str:
    """The repo whose bead list takes this cause: task-loop, delegate, or the project most of its runs ran in."""
    repos = registered() if repos is None else repos
    want = OWNERS.get(c["cause"])
    if want:
        for p in repos:
            if Path(p).name == want:
                return p
    mine = Counter[str]()
    for r_, n in c["repos"].items():
        hit = resolve_repo(r_, repos)
        if hit:
            mine[hit] += n
    return mine.most_common(1)[0][0] if mine else ""


def known_bead(c: dict[str, Any], repo: str, state: dict[str, Any]) -> tuple[str, str]:
    """-> (bead id, why) of the bead that already carries this cause: the state file's, else an open bead of the repo with a like
    title; ('', '') when none."""
    for e in reversed(state.get("filed", [])):  # the newest first: a closed one's successor wins
        if e.get("cause") == c["cause"] and e.get("repo") == repo and same_cause(e, c):
            return e["bead"], "filed"
    rows: list[Any]
    try:
        rows = beadtools.bd_store(repo).find(BeadQuery())  # the default filter leaves out closed beads only
    except BdFailure:
        rows = []
    ct = tokens(c["title"])
    for b in rows:
        if jaccard(tokens(b.title), ct) >= TITLE_SIMILAR:
            return b.id, "open"
    return "", ""


def is_closed(bead: BeadId, repo: str) -> bool:
    row = beadtools.peek(beadtools.bd_store(repo), bead)
    return row is not None and row.status == "closed"


def _update_known(c: dict[str, Any], repo: str, bead: str, state: dict[str, Any], dry: bool, res: dict[str, Any]) -> dict[str, Any]:
    """The cause already has a bead: comment on it the runs it has not been told of."""
    entry: dict[str, Any] | None = next((e for e in state.get("filed", []) if e.get("bead") == bead and e.get("repo") == repo), None)
    if entry is None:  # an open bead found by title: remember it, so its runs are commented once
        entry = {"cause": c["cause"], "repo": repo, "bead": bead, "tokens": sorted(c["tokens"]), "files": c["files"], "runs": [],
                 "at": time.time()}
        if not dry:
            state.setdefault("filed", []).append(entry)
    new = [r_ for r_ in c["runs"] if r_ not in entry["runs"]]
    res.update(bead=bead, action="skipped")
    if new:
        res["action"] = "commented"
        if not dry:
            beadtools.attempt(
                beadtools.bd_store(repo).add_comment,
                bead,
                "Reflect digest: the cause recurred in {:d} more run(s): {}\n{}".format(
                    len(new), ", ".join(new), "\n".join(evidence_lines(dict(c, items=[i for i in c["items"] if i["run"] in new])))
                ),
            )
            entry["runs"] = sorted(set(entry["runs"]) | set(new))
    return res


def file_cluster(c: dict[str, Any], state: dict[str, Any], dry: bool = False, repos: Sequence[str] | None = None) -> dict[str, Any]:
    """File or update the bead for one recurring cause. -> {action: filed|commented|skipped|none, bead, repo, cause, runs}."""
    repo = owner_repo(c, repos)
    res = {"cause": c["cause"], "title": c["title"], "repo": repo, "runs": c["runs"], "bead": "", "action": "none"}
    if not repo:
        return res
    bead, why = known_bead(c, repo, state)
    old = ""
    if is_bead_id(bead) and why == "filed" and is_closed(bead, repo):
        for e in state.get("filed", []):
            if e.get("bead") == bead and e.get("repo") == repo:
                e["closed"] = True  # its successor takes the cause from here
        old, bead = bead, ""
    if bead:
        return _update_known(c, repo, bead, state, dry, res)
    title = "Reflect: {}: {}".format(c["cause"], c["title"])
    res["action"] = "filed"
    if dry:
        return res
    try:
        new_id = beadtools.bd_store(repo).create(NewBead(title=title, priority=3, labels=["reflect", "cause-{}".format(c["cause"])],
                                                  description=description(c, old), acceptance_criteria=acceptance(c)))
    except BdFailure:
        new_id = ""
    if not new_id:
        res["action"] = "failed"
        return res
    res["bead"] = new_id
    state.setdefault("filed", []).append({"cause": c["cause"], "repo": repo, "bead": new_id, "tokens": sorted(c["tokens"]),
                                          "files": c["files"], "runs": c["runs"], "at": time.time()})
    return res


def digest(since: float, until: float, dry: bool = False, traces: str | Path | None = None,
           repos: Sequence[str] | None = None) -> dict[str, Any]:
    """-> {window, clusters: [...], actions: [...]}. Files and updates beads unless dry; one digest at a time (a manual run and
    the daily one never both file the cause), the state saved after every bead so a crash loses none."""
    if dry:
        return _digest(since, until, True, traces, repos)
    try:
        with landlock.os_lock(ident.config_dir() / "locks" / "reflect-digest-run.lock", f"pid {os.getpid()}", timeout=120):
            return _digest(since, until, False, traces, repos)
    except TimeoutError:
        return {"since": since, "until": until, "items": 0, "clusters": [], "actions": [], "busy": True}


def _digest(since: float, until: float, dry: bool, traces: str | Path | None, repos: Sequence[str] | None) -> dict[str, Any]:
    cs = cluster(items(since, until, traces))
    out: dict[str, Any] = {"since": since, "until": until, "items": sum(len(c["items"]) for c in cs), "clusters": [], "actions": []}
    state = read_state()
    for c in cs:
        row = {"cause": c["cause"], "title": c["title"], "runs": len(c["runs"]), "run_ids": c["runs"], "beads": c["beads"],
               "files": c["files"], "recurring": is_recurring(c)}
        out["clusters"].append(row)
        if row["recurring"]:
            a = file_cluster(c, state, dry, repos)
            out["actions"].append(a)
            row["bead"], row["repo"] = a["bead"], a["repo"]
            if not dry and a["action"] in ("filed", "commented"):
                write_state(state)
    return out


def due(now: float | None = None) -> bool:
    return (now or time.time()) - float(read_state().get("tried") or 0) >= DAY


def maybe_run(spawner: Spawner, now: float | None = None) -> str:
    """The loop's call: once a day a detached `tl reflect digest` (it asks bd about every open bead of the target repos: a loop
    pass never waits for it). -> 'started' or ''."""
    if not due(now) or not (ident.config_dir() / "traces.jsonl").is_file() or not registered():
        return ""  # nothing to read or nowhere to file
    try:
        with landlock.os_lock(ident.config_dir() / "locks" / "reflect-digest.lock", f"pid {os.getpid()}"):
            if not due(now):
                return ""
            pass
        spawner.start([*childenv.script_argv(ident.PLUGIN_ROOT / "skills" / "task-loop" / "tl.py"), "reflect", "digest"])
        st = read_state()
        st["tried"] = now or time.time()
        write_state(st)
    except OSError:
        return ""
    return "started"

