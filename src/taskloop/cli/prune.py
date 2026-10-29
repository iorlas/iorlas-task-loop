"""The verb `tl prune [--dry-run]`: find the repo and the machine's registered ones, hand them to app/prune."""
from collections.abc import Callable
from typing import Any

from taskloop.app.launch import loop as wloop
from taskloop.app.launch import repos
from taskloop.app.prune import verb
from taskloop.app.track import trail


def cmd_prune(a: Any, now: Callable[[], float] = trail.now) -> int:
    repo = repos.repo_root(a.repo)
    verb.run(wloop.cfgdir(), wloop.profile_of(repo).loop, wloop.prune_repos(repo), wloop.bd_of, now(), a.dry_run)
    return 0
