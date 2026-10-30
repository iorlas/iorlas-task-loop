"""One sweep: observe, diff, apply. `tl prune`'s build trees, release branches and landed task branches all go through it."""
from collections.abc import Callable
from pathlib import Path

from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import Live, observe
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads, Git
from taskloop.domain.reconcile.diff import diff


def sweep(repos: list[str], store_of: Callable[[str], Beads] | None, build: Path | None, days: float, now: float, dry_run: bool,
          git: Git, cfg: ConfigDir | None = None, live_of: Live | None = None,
          host: str = "") -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason). `live_of`: the runs running now (leases and slots are swept only
    when it is given). The dry run prints the plan, the real run executes exactly it."""
    seen = observe(repos, store_of, build, days, now, git, cfg, live_of, host)
    return apply(diff(seen), dry_run, git, store_of)
