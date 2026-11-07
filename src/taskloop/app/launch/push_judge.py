"""Compose the push judge: it reads the receipts `tl check` / `tl land-stack` wrote and runs nothing."""
import argparse
import sys

from taskloop.adapters import landlock, locks
from taskloop.app.land.push_judge import judge_push
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.procport import Spawner
from taskloop.stores.real import real_stores

GUARD_MAIN = False  # dark: the rollout flips it, with the ruleset in place (docs/design/merge-queue.md 8.1)


def land_lock_holder(repo: str, who: Identity, git: Git) -> str:
    """Who holds the repo's land lock right now ('' when nobody wrote a holder)."""
    rec = locks.read_holder(landlock.land_lock_path(who.config, git.remote_url(repo, "origin") or repo))
    return rec.holder if rec else ""


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    holder = land_lock_holder(a.repo, who, git) if GUARD_MAIN else ""
    decision = judge_push(a.repo, sys.stdin.read(), real_stores(who.config), git, env=env, guard_main=GUARD_MAIN, lock_holder=holder)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
