"""`tl green STEP --repo DIR --tree T --base B`: resolve the judged requirement and require its complete stored evidence.
Exit 0 green, 1 not; one line. Another runner asks this instead of re-running the step."""
import argparse
from collections.abc import Callable
from pathlib import Path

from taskloop.app.checks import authorization
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.real import real_stores

GREEN, NOT_GREEN = 0, 1


def cmd_green(a: argparse.Namespace, cfg: ConfigDir, git: Git, out: Callable[[str], None] = print, *, env: Env | None = None) -> int:
    wt, tree, base, step = str(Path(a.repo).resolve()), TreeSha(a.tree), BaseSha(a.base), CheckId(a.step)
    try:
        engine = authorization.profile(git, wt, tree)
        res = authorization.results(real_stores(cfg), git, wt, engine, tree, base, env or Env(), step).get(step)
    except (OSError, ValueError, SlotGitError):
        res = None
    ok = res is not None
    why = f" (skipped-by-plan: {res.why})" if res is not None and res.planned else " (passed)" if ok else ""
    out(f"{'green' if ok else 'not green'}: {a.step} tree {a.tree} base {a.base}{why}")
    return GREEN if ok else NOT_GREEN


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("green", help="does the resolved check have evidence for a tree and base (exit 0 green, 1 not)",
                      formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", metavar="STEP", help="the check id")
    p.add_argument("--repo", default=".", metavar="DIR", help="the repo's worktree (default: the current directory)")
    p.add_argument("--tree", required=True, metavar="SHA", help="the worktree's tree hash")
    p.add_argument("--base", required=True, metavar="SHA", help="the base commit sha")
