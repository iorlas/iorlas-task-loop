"""What `tl prune` does to run data: the three sweeps that already exist (check-round logs, run folders, engine logs) with one age, the
event log trimmed to it, and nothing of a bead that is still open or parked."""
import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.run import layout
from taskloop.app.track import trail
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads


@dataclass(frozen=True)
class Gone:
    path: Path
    bytes: int


def size_of(path: Path) -> int:
    total = 0
    for dirpath, _, names in os.walk(path):
        for n in names:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, n)).st_size
    return total or (path.lstat().st_size if path.is_file() else 0)


def open_beads(repos: list[str], store_of: Callable[[str], Beads]) -> tuple[set[str], str]:
    """(the ids of every bead not closed in these repos: open, in progress, blocked, parked; why that could not be asked, else "").
    A repo whose bd does not answer leaves its beads unknown: the caller keeps all run data then."""
    found: set[str] = set()
    for repo in repos:
        try:
            found |= {b.id for b in store_of(repo).find(BeadQuery())}
        except (BdFailure, SystemExit, OSError) as e:
            return set(), f"bd did not answer in {repo} ({str(getattr(e, 'error', e))[:80]})"
    return found, ""


def prune_runs(cfg: ConfigDir, days: float, exempt: set[str], now: float, dry_run: bool) -> list[Gone]:
    """Run folders, check-round logs and engine logs older than `days` (a bead in `exempt` keeps all of them), then the event log.
    -> what went, or with `dry_run` what would."""
    runs = cfg.root / "runs"
    dirs = layout.prune_run_dirs(runs, days, exempt, True)
    rounds = [f for f in layout.prune_check_rounds(runs, days, exempt, True) if not any(d in f.parents for d in dirs)]
    logs = layout.prune_run_logs(cfg, now, days * 86400, exempt, True)
    suites = [f for f in cfg.suite_logs() if f.stat().st_mtime < now - days * 86400]
    found = [Gone(p, size_of(p)) for p in [*dirs, *rounds, *logs, *suites] if p.exists()]
    if not dry_run:
        for f in suites:
            f.unlink(missing_ok=True)
        layout.prune_run_dirs(runs, days, exempt)
        layout.prune_check_rounds(runs, days, exempt)
        layout.prune_run_logs(cfg, now, days * 86400, exempt)
        trail.prune_events(days)
    return found
