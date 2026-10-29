"""`tl prune [--dry-run]`: the run data, build trees and release branches that are past `loop.keep_days`, removed; what stays, with why.
Idempotent: a second run finds nothing. The loop runs it at its start."""
from collections.abc import Callable
from pathlib import Path

from taskloop.app.prune import runs, trees
from taskloop.app.release.shell import REAL, Shell
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads


def mb(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB"


def run(cfg: ConfigDir, loop: LoopConfig, repos: list[str], store_of: Callable[[str], Beads], now: float, dry_run: bool,
        say: Callable[[str], None] = print, sh: Shell = REAL) -> int:
    """Prune once. -> how many things went (would, with `dry_run`)."""
    would = "would remove " if dry_run else "removed "
    exempt, why = runs.open_beads(repos, store_of)
    count = 0
    if why:
        say(f"prune: run data kept: {why}")
    else:
        old = Path(cfg.root / "runs")
        folders = [d for d in old.glob("*") if d.is_dir()] if old.is_dir() else []
        gone = runs.prune_runs(cfg, loop.keep_days, exempt, now, dry_run)
        for g in gone:
            say(f"prune: {would}{g.path} ({mb(g.bytes)})")
        count += len(gone)
        held = sum(1 for d in folders if d.name.rsplit("-", 2)[0] in exempt)
        say(f"prune: run data: {would}{len(gone)} item(s), {mb(sum(g.bytes for g in gone))}; kept every run folder newer than "
            f"{loop.keep_days:g} days and {held} of beads still open or parked")
    removed, kept = trees.prune_trees(Path(loop.build_dir).expanduser(), repos, loop.keep_days, now, dry_run, sh)
    for line in removed:
        say(f"prune: {line if dry_run else 'removed ' + line}")
    for line in kept:
        say(f"prune: kept {line}")
    return count + len(removed)
