"""`tl prune [--dry-run]`: the run data past `loop.keep_days`, then one reconcile sweep (build trees, release branches, landed task
branches, and the claims and slots whose lease ended with no live run), removed; what stays, with why.
Idempotent: a second run finds nothing. The loop runs it at its start."""
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters.ident import hostname
from taskloop.app.prune import runs
from taskloop.app.reconcile.sweep import sweep
from taskloop.app.release.shell import Shell
from taskloop.app.run import running
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads


def mb(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB"


def run(cfg: ConfigDir, loop: LoopConfig, repos: list[str], store_of: Callable[[str], Beads], now: float, dry_run: bool,
        sh: Shell, say: Callable[[str], None] = print, *, who: Identity) -> int:
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
    gone, stays = sweep(repos, store_of, Path(loop.build_dir).expanduser(), loop.keep_days, now, dry_run, sh.port, None,
                        lambda repo: running.running(repo, sh.port, who, store_of(repo)), hostname())
    for line in gone:
        say(f"prune: {line if dry_run else 'removed ' + line}")
    for line in stays:
        say(f"prune: kept {line}")
    return count + len(gone)
