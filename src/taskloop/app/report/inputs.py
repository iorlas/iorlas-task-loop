"""What `tl report` reads: traces.jsonl, the engine logs, the repo's git refs (never fetched), bd. Reads only."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tlkernel.beadsport import BdFailure, Beads
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.landed import Landed, landed_by
from tlkernel.paths import ConfigDir
from tlkernel.slots import git_probe
from tlkernel.trace import RunTrace

from taskloop.adapters import beadtools
from taskloop.adapters.bdids import prefix_of
from taskloop.stores.real import real_stores


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
    url = git_probe(lambda: git.remote_url(repo, "origin"), "")
    page = real_stores(cfg).traces.read_from(0)
    out: list[RunTrace] = []
    for item in page.items:
        t = item.rec
        inside = bool(t.worktree) and (str(Path(t.worktree).resolve()) + os.sep).startswith(root + os.sep)
        if inside or (url and t.repo_url == url):
            out.append(t)
    return Traces(out, page.skipped)


def prefix(bead: str | None) -> str:
    return prefix_of(bead)


def landed_of(bead: BeadId, repo: str, who: Identity) -> Landed | None:
    """The bead's landed record from the tracker (None: it has none, or bd did not answer)."""
    return landed_by(beadtools.bd_store(who.actor, repo))(bead)


def bead_status(bead: BeadId, repo: str, who: Identity, store: Beads | None = None) -> str | None:
    """The bead's status, None when the tracker has no such bead, "?" when bd itself failed (no false lost work)."""
    try:
        found = (store or beadtools.bd_store(who.actor, repo)).show(bead)
    except BdFailure:
        return "?"
    return found.status if found else None

