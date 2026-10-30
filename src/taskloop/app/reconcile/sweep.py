"""One sweep: observe, diff, apply. `tl prune`'s build trees, release branches and landed task branches all go through it."""
from collections.abc import Callable
from pathlib import Path

from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import observe
from taskloop.app.release.shell import Shell
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads
from taskloop.domain.reconcile.diff import diff


def sweep(repos: list[str], store_of: Callable[[str], Beads] | None, build: Path | None, days: float, now: float, dry_run: bool,
          sh: Shell, cfg: ConfigDir | None = None) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason). The dry run prints the plan, the real run executes exactly it."""
    return apply(diff(observe(repos, store_of, build, days, now, sh, cfg)), dry_run, sh)
