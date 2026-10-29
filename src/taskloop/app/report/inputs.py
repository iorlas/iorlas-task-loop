"""What `tl report` reads: traces.jsonl, the engine logs, the repo's git refs (never fetched), bd. Reads only."""
import json
import os
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools, gitrepo, ident
from taskloop.adapters import procs as sproc
from taskloop.contracts.ports import BdFailure, Beads


def git(repo: str, *args: str) -> str:
    return gitrepo.git(*args, cwd=repo)


def bases_of(repo: str, base: str) -> list[str]:
    """The base and its local or remote twin, those that exist: a stale local main must not hide a land on origin."""
    names = [base]
    if base.startswith("origin/"):
        names.append(base[len("origin/"):])
    else:
        names.append("origin/" + base)
    return [n for n in names if git(repo, "rev-parse", "--verify", "-q", n + "^{commit}")]


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def repo_traces(repo: str) -> list[dict[str, Any]]:
    """Every engine run of this repo: its worktree is inside the repo, or its origin is the repo's origin."""
    root = str(Path(repo).resolve())
    url = git(repo, "remote", "get-url", "origin")
    out: list[dict[str, Any]] = []
    for r in read_jsonl(ident.config_dir() / "traces.jsonl"):
        wt = r.get("worktree") or ""
        inside = bool(wt) and (str(Path(wt).resolve()) + os.sep).startswith(root + os.sep)
        if inside or (url and r.get("repo") == url):
            out.append(r)
    return out


def run_alive(bead: str) -> bool | None:
    """A run-task of this bead is a live process (from /proc); None when that cannot be told."""
    rows = sproc.table()
    if rows is None:
        return None
    return any("run-task" in p.cmd and bead in p.cmd.split() for p in rows.values())


def prefix(bead: str | None) -> str:
    return (bead or "").split("-")[0]


def bead_status(bead: str, repo: str, store: Beads | None = None) -> str | None:
    """The bead's status, None when the tracker has no such bead, "?" when bd itself failed (no false lost work)."""
    try:
        found = (store or beadtools.bd_store(repo)).show(bead)
    except BdFailure:
        return "?"
    return found.status if found else None

