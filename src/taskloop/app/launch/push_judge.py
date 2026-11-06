"""Compose the push judge: it reads the receipts `tl check` / `tl land-stack` wrote and runs nothing."""
import argparse
import sys

from taskloop.app.land.push_judge import judge_push
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ports import Git, Spawner
from taskloop.stores.real import real_stores


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    decision = judge_push(a.repo, sys.stdin.read(), real_stores(who.config), git, env=env)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
