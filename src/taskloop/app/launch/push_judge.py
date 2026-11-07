"""Compose the push judge: it reads the receipts `tl check` / `tl land-stack` wrote and runs nothing."""
import argparse
import sys

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.procport import Spawner

from taskloop.adapters.land_probe import land_lock_held
from taskloop.app.land.push_judge import judge_push
from taskloop.stores.real import real_stores

GUARD_MAIN = False  # dark: the rollout flips it, with the ruleset in place (docs/design/merge-queue.md 8.1)


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    held = GUARD_MAIN and land_lock_held(who.config, git, a.repo)
    stores = real_stores(who.config)
    decision = judge_push(a.repo, sys.stdin.read(), stores, git,
                          profile_changes=stores.profile_changes, env=env, guard_main=GUARD_MAIN, land_lock_held=held)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
