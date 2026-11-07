"""The verb `tl prune [--dry-run]`: find the repo and the machine's registered ones, hand them to app/prune."""
from collections.abc import Callable
from typing import Any

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity

from taskloop.app.launch import loop as wloop
from taskloop.app.launch import repos
from taskloop.app.prune import verb
from taskloop.app.release import shell
from taskloop.app.run import running
from taskloop.app.track import trail
from taskloop.app.wire import real


def cmd_prune(a: Any, env: Env, git: Git, who: Identity, now: Callable[[], float] = trail.now) -> int:
    repo = repos.repo_root(a.repo)
    verb.run(
        who.config,
        wloop.profile_of(repo, git).loop,
        wloop.prune_repos(repo, who.config),
        lambda r: wloop.bd_of(who, r),
        now(),
        a.dry_run,
        shell.of(real.spawner(env), git, env),
        live=lambda r: running.running(r, git, who, wloop.bd_of(who, r)),
    )
    return 0
