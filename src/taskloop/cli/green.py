"""`tl green STEP --bead ID --tree T --base B`: is the step green for that tree and base, answered from the check memo
(check-cache/<bead>.json) and nothing else. Exit 0 green, 1 not; one line. Another runner asks this instead of re-running the step."""
import argparse
from collections.abc import Callable

from taskloop.app.checks.cache import is_green
from taskloop.contracts.checks import CheckCacheEntry
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.files import FileDocSet

GREEN, NOT_GREEN = 0, 1


def cmd_green(a: argparse.Namespace, cfg: ConfigDir, out: Callable[[str], None] = print) -> int:
    entry = FileDocSet(cfg.check_cache, CheckCacheEntry).of(a.bead).get()
    ok = is_green(entry, CheckId(a.step), TreeSha(a.tree), BaseSha(a.base))
    out(f"{'green' if ok else 'not green'}: {a.step} tree {a.tree} base {a.base}")
    return GREEN if ok else NOT_GREEN


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("green", help="is a check step green for a tree and base, from the check memo (read-only; exit 0 green, 1 not)",
                      formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", metavar="STEP", help="the check id")
    p.add_argument("--bead", required=True, metavar="ID", help="the bead whose memo is asked")
    p.add_argument("--tree", required=True, metavar="SHA", help="the worktree's tree hash")
    p.add_argument("--base", required=True, metavar="SHA", help="the base commit sha")
