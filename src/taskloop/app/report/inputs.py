"""What `tl report` reads: traces.jsonl, the engine logs, the repo's git refs (never fetched), bd. Reads only."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, Beads, Git
from taskloop.contracts.stores import TraceStore
from taskloop.contracts.trace import RunTrace


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


@dataclass(frozen=True)
class Traces:
    """The traces of one repo, and how many lines of traces.jsonl were not a RunTrace of this version (skipped, never guessed at)."""
    runs: list[RunTrace]
    skipped: int


def repo_traces(repo: str, git: Git, cfg: ConfigDir) -> Traces:
    """Every engine run of this repo: its worktree is inside the repo, or its origin is the repo's origin."""
    root = str(Path(repo).resolve())
    url = git.remote_url(repo, "origin")
    page = TraceStore(cfg).read_from(0)
    out: list[RunTrace] = []
    for item in page.items:
        t = item.rec
        inside = bool(t.worktree) and (str(Path(t.worktree).resolve()) + os.sep).startswith(root + os.sep)
        if inside or (url and t.repo_url == url):
            out.append(t)
    return Traces(out, page.skipped)


def prefix(bead: str | None) -> str:
    return (bead or "").split("-")[0]


def bead_status(bead: BeadId, repo: str, who: Identity, store: Beads | None = None) -> str | None:
    """The bead's status, None when the tracker has no such bead, "?" when bd itself failed (no false lost work)."""
    try:
        found = (store or beadtools.bd_store(who.actor, repo)).show(bead)
    except BdFailure:
        return "?"
    return found.status if found else None

