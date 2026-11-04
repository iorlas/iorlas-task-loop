"""Compose the push judge with the same standalone check service used by `tl check`."""
import argparse
import sys

from taskloop.app.land.push_judge import judge_push
from taskloop.app.launch.check import cmd_check
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ports import Git, Spawner
from taskloop.stores.real import real_stores


def cmd_judge_push(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git) -> int:
    def check(policy: EngineConfig) -> int:
        if a.no_run:
            return 1  # evidence only: the judge names the steps without a receipt and refuses
        args = argparse.Namespace(cmd="check", repo=a.repo, ids=[], all=False, staged=False, list=False, policy_commit=None)
        return cmd_check(args, who=who, env=env, spawner=spawner, git=git, policy=policy)

    decision = judge_push(a.repo, sys.stdin.read(), real_stores(who.config), git, check, env=env, spawner=spawner)
    for reason in decision.reasons:
        print(f"tl pre-push: refused: {reason}", file=sys.stderr)
    return int(decision.status)
