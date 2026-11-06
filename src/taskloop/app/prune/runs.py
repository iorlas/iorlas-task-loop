"""One retention age for run files, factory history and trace logs; open beads and live runs stay."""
import contextlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.prune.traces import prune_traces
from taskloop.app.run import layout
from taskloop.app.track import trail
from taskloop.contracts import factorydb
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.beadsport import BdFailure, BeadQuery, Beads
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runlife import KEEP_DAYS


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
        except (BdCommandFailure, BdFailure, SystemExit, OSError) as e:
            return set(), f"bd did not answer in {repo} ({str(getattr(e, 'error', e))[:80]})"
    return found, ""


def kept_days(configured: float) -> float:
    """The age past which run data of a closed bead goes: the configured one, never under KEEP_DAYS."""
    return max(configured, KEEP_DAYS)


def bundles_for_prune(cfg: ConfigDir) -> list[RunBundle]:
    """Discovery must neither create a missing DB nor fail the verb on an unavailable one."""
    try:
        return RunLocator(cfg).runs() if cfg.factory_db().exists() else []
    except (factorydb.DatabaseError, OSError):
        return []


def prune_runs(cfg: ConfigDir, days: float, exempt: set[str], now: float, dry_run: bool,
               say: Callable[[str], None] = print) -> list[Gone]:
    """Prune files, DB history and traces with kept_days(days), exemptions and one dry-run plan.

    Return the existing Gone list for files; report history/trace row counts through say.
    Unavailable databases keep all run data. A missing database is never created.
    """
    days = kept_days(days)
    con = None
    try:
        try:
            if cfg.factory_db().exists():
                con = factorydb.open_rw(cfg.factory_db())
                if con is None:
                    say("prune: factory.db history kept: database unavailable")
                    return []
            bundles = RunLocator(cfg).runs() if con is not None else []
        except (factorydb.DatabaseError, OSError):
            say("prune: factory.db history kept: database unavailable")
            return []
        protected = exempt | {b.bead for b in bundles if b.manifest.state.live}
        gone = _prune_files(cfg, days, protected, now, dry_run, bundles)
        would = "would remove" if dry_run else "removed"
        if con is not None:
            counts = factorydb.prune_older_than(con, now - days * 86400, keep_beads=frozenset(exempt), dry_run=dry_run)
            summary = ", ".join(f"{n} {table}(s)" for table, n in counts.items())
            say(f"prune: factory.db history: {would} {summary}")
        rows = prune_traces(cfg, days, now, dry_run, frozenset(protected))
        say(f"prune: traces.jsonl: {would} {rows} row(s)")
        return gone
    finally:
        if con is not None:
            con.close()


def _prune_files(cfg: ConfigDir, days: float, exempt: set[str], now: float, dry_run: bool,
                 bundles: list[RunBundle]) -> list[Gone]:
    """Scan before deleting DB manifests, so each run's files remain discoverable."""
    dirs = layout.prune_run_dirs(cfg, days, exempt, True) if bundles else []
    rounds = [f for f in layout.prune_check_rounds(cfg, days, exempt, True)
              if not any(d in f.parents for d in dirs)] if bundles else []
    logs = layout.prune_run_logs(cfg, now, days * 86400, exempt, True) if bundles else []
    suites = [f for f in cfg.suite_logs() if f.stat().st_mtime < now - days * 86400]
    found = [Gone(p, size_of(p)) for p in [*dirs, *rounds, *logs, *suites] if p.exists()]
    if not dry_run:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)
        for f in rounds:
            f.unlink(missing_ok=True)
        for b in bundles:
            if b.log in logs:
                with contextlib.suppress(OSError):
                    layout.drop_run_log(cfg, b)
        for f in suites:
            f.unlink(missing_ok=True)
        trail.prune_events(cfg, days)
    return found
