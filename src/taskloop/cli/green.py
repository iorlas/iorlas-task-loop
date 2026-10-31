"""`tl green STEP --repo DIR --tree T --base B`: is the step green for that tree and base, answered from the repo's result store
(results/<repo>/) and nothing else. Exit 0 green, 1 not; one line. Another runner asks this instead of re-running the step."""
import argparse
from collections.abc import Callable
from pathlib import Path

from taskloop.app.checks.cache import repo_green_result
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.real import real_stores

GREEN, NOT_GREEN = 0, 1


def cmd_green(a: argparse.Namespace, cfg: ConfigDir, git: Git, out: Callable[[str], None] = print) -> int:
    res = repo_green_result(real_stores(cfg), git, str(Path(a.repo).resolve()), CheckId(a.step), TreeSha(a.tree), BaseSha(a.base))
    ok = res is not None
    why = f" (skipped-by-plan: {res.why})" if res is not None and res.planned else " (passed)" if ok else ""
    out(f"{'green' if ok else 'not green'}: {a.step} tree {a.tree} base {a.base}{why}")
    return GREEN if ok else NOT_GREEN


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("green", help="is a check step green for a tree and base, from the result store (read-only; exit 0 green, 1 not)",
                      formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", metavar="STEP", help="the check id")
    p.add_argument("--repo", default=".", metavar="DIR", help="the repo's worktree (default: the current directory)")
    p.add_argument("--tree", required=True, metavar="SHA", help="the worktree's tree hash")
    p.add_argument("--base", required=True, metavar="SHA", help="the base commit sha")
