"""`tl setup (--plan | --apply) [--repo DIR] [--json] [--answers FILE | --yes]`: what a machine and a repo still need, and making it so.
--plan looks only. --apply makes the safe machine fixes and, for a repo with no profile, opens a PR with the owner's answers."""
import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path

from tlkernel.env import Env

from taskloop.app.doctor import setup, setup_apply
from taskloop.app.launch import setup_ports


def answers_of(a: argparse.Namespace, repo: Path, facts: setup.ProfileFacts) -> dict[str, str]:
    """--answers FILE (a JSON object of question id -> answer) over --yes (every default)."""
    given = {q.id: q.default for q in setup.repo_part(repo, facts).questions} if a.yes else {}
    if a.answers:
        given.update({str(k): str(v) for k, v in json.loads(Path(a.answers).read_text(encoding="utf-8")).items()})
    return given


def cmd_setup(a: argparse.Namespace, env: Env, plugin_root: Path, out: Callable[[str], None] = print,
              sh: setup_apply.Runs | None = None) -> int:
    repo = Path(a.repo or os.getcwd())
    if a.apply:
        if sh is None:
            raise SystemExit("tl setup --apply needs a spawner")
        code, lines = setup_apply.apply(plugin_root, env, repo, answers_of(a, repo, setup_ports.facts), sh, setup_ports.facts,
                                       setup_ports.route(), setup_ports.host_store(env))
        out("\n".join(lines))
        return code
    plan = setup.plan(plugin_root, env, repo, setup_ports.facts, setup_ports.route())
    out(setup.as_json(plan) if a.json else setup.render(plan))
    return 0 if all(c.ok for c in plan.checks) else 1


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("setup", help="what this machine and repo still need (--plan, writes nothing), or make it so (--apply)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="look only: checks, safe fixes and the questions for the owner")
    mode.add_argument("--apply", action="store_true", help="make the safe machine fixes; open a PR with the profile the answers describe")
    p.add_argument("--repo", metavar="DIR", help="the repo to look at (default: the current directory)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--answers", metavar="FILE", help="a JSON object of question id -> answer")
    p.add_argument("--yes", action="store_true", help="answer every question with its default")
