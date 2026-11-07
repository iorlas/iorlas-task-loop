"""Compose the push judge: it reads the receipts `tl check` / `tl land-stack` wrote and runs nothing."""
import argparse
import sys

from taskloop.adapters import landlock, locks
from taskloop.app.land.push_judge import judge_push
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.procport import Spawner
from taskloop.stores.real import real_stores

GUARD_MAIN = False  # dark: the rollout flips it, with the ruleset in place (docs/design/merge-queue.md 8.1)


def land_lock_held(repo: str, who: Identity, git: Git) -> bool:
    """Whether someone holds the repo's land lock now: a land push and a release take it around their push to main."""
    try:
        with locks.hold_path(landlock.land_lock_path(who.config, git.remote_url(repo, "origin") or repo), "judge-probe", timeout=0):
            return False
    except LockTimeout:
        return True


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    held = land_lock_held(a.repo, who, git) if GUARD_MAIN else False
    decision = judge_push(a.repo, sys.stdin.read(), real_stores(who.config), git, env=env, guard_main=GUARD_MAIN, land_lock_held=held)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
