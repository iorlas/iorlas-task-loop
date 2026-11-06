"""`tl prune [--dry-run]`: run files, factory.db history and traces.jsonl past the retention age, then one reconcile sweep
(build trees, release branches, landed task
branches, and the claims and slots whose lease ended with no live run), removed; what stays, with why.
Idempotent: a second run finds nothing. The loop runs it at its start."""
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters.ident import hostname
from taskloop.app.prune import retention, runs
from taskloop.app.reconcile.sweep import sweep
from taskloop.app.release.shell import Shell
from taskloop.app.run import running
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads
from taskloop.contracts.rowstores import ReposStore


def mb(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB"


def _forget_missing(cfg: ConfigDir, dry_run: bool, say: Callable[[str], None]) -> None:
    """repos.json: an entry whose folder is gone is dropped (named only, with `dry_run`)."""
    store = ReposStore(cfg)
    if dry_run:
        gone = [n for n, e in store.index().repos.items() if not Path(e.path).is_dir()]
    else:
        gone = store.drop_missing(lambda p: Path(p).is_dir())
    for name in gone:
        say(f"prune: {'would drop' if dry_run else 'dropped'} repo {name}: its folder is gone")


def run(cfg: ConfigDir, loop: LoopConfig, repos: list[str], store_of: Callable[[str], Beads], now: float, dry_run: bool,
        sh: Shell, say: Callable[[str], None] = print, *, who: Identity) -> int:
    """Prune once. -> how many things went (would, with `dry_run`)."""
    would = "would remove " if dry_run else "removed "
    _forget_missing(cfg, dry_run, say)
    exempt, why = runs.open_beads(repos, store_of)
    count = 0
    if why:
        say(f"prune: run data kept: {why}")
    else:
        folders = runs.bundles_for_prune(cfg)
        gone = runs.prune_runs(cfg, loop.keep_days, exempt, now, dry_run, say)
        for g in gone:
            say(f"prune: {would}{g.path} ({mb(g.bytes)})")
        count += len(gone)
        held = sum(1 for d in folders if d.bead in exempt)
        say(f"prune: run data: {would}{len(gone)} item(s), {mb(sum(g.bytes for g in gone))}; kept every run folder newer than "
            f"{runs.kept_days(loop.keep_days):g} days and {held} of beads still open or parked")
    logs = retention.prune(cfg, loop.keep_days, now, dry_run)
    for g in logs:
        say(f"prune: {would}{g.path} ({mb(g.bytes)})")
    count += len(logs)
    gone, stays = sweep(repos, store_of, Path(loop.build_dir).expanduser(), loop.keep_days, now, dry_run, sh.port, cfg,
                        lambda repo: running.running(repo, sh.port, who, store_of(repo)), hostname())
    for line in gone:
        say(f"prune: {line if dry_run else 'removed ' + line}")
    for line in stays:
        say(f"prune: kept {line}")
    return count + len(gone)
