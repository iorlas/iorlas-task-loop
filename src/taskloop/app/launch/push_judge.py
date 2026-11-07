"""Compose the push judge: it reads the receipts `tl check` / `tl land-stack` wrote and runs nothing."""
import argparse
import sys

from taskloop.app.land.push_judge import judge_push, land_lock_held
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.procport import Spawner
from taskloop.stores.real import real_stores

GUARD_MAIN = False  # dark: the rollout flips it, with the ruleset in place (docs/design/merge-queue.md 8.1)


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    held = GUARD_MAIN and land_lock_held(who.config, git, a.repo)
    decision = judge_push(a.repo, sys.stdin.read(), real_stores(who.config), git, env=env, guard_main=GUARD_MAIN, land_lock_held=held)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
