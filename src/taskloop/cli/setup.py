"""`tl setup --plan [--repo DIR] [--json]`: what a machine and a repo still need, read-only (the prototype of the skill's first command)."""
import argparse
import os
from collections.abc import Callable
from pathlib import Path

from taskloop.app.wire import setup
from taskloop.contracts.env import Env


def cmd_setup(a: argparse.Namespace, env: Env, plugin_root: Path, out: Callable[[str], None] = print) -> int:
    plan = setup.plan(plugin_root, env, Path(a.repo or os.getcwd()))
    out(setup.as_json(plan) if a.json else setup.render(plan))
    return 0 if all(c.ok for c in plan.checks) else 1


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("setup", help="what this machine and repo still need (read-only; writes nothing)")
    p.add_argument("--plan", action="store_true", required=True, help="look only: checks, safe fixes and the questions for the owner")
    p.add_argument("--repo", metavar="DIR", help="the repo to look at (default: the current directory)")
    p.add_argument("--json", action="store_true")
