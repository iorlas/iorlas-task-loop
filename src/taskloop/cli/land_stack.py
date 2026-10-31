"""`tl land-stack ITEM...`: deliver existing PRs, branches or a stack of both, lowest first, as one run (app/land/stack.py)."""
import argparse
import socket
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.app.land.cmds import Cmds
from taskloop.app.land.forge import Forge
from taskloop.app.land.stack import Stack, lock_path
from taskloop.contracts.forge import StackItem
from taskloop.contracts.identity import Identity
from taskloop.contracts.ports import Beads, Git, Spawner
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


def item_of(text: str, beads: dict[str, str], supersedes: dict[str, str]) -> StackItem:
    """An argument: a PR number or url, or a branch name. `beads` and `supersedes` are keyed by that same text."""
    tail = text.rstrip("/").rpartition("/pull/")[2] if "/pull/" in text else text
    pr = int(tail) if tail.isdigit() else 0
    old = supersedes.get(text, "")
    return StackItem(branch="" if pr else text, pr=pr, bead=beads.get(text, ""), supersedes=int(old) if old else 0)


def pairs(values: list[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values:
        key, eq, val = v.partition("=")
        if not eq or not key or not val:
            raise SystemExit(f"land-stack: {flag} wants ITEM=VALUE, got {v!r}")
        out[key] = val
    return out


def cmd_land_stack(a: argparse.Namespace, who: Identity, git: Git, spawner: Spawner, store: Beads,
                   record: Callable[[str, str], int]) -> int:
    """`record(bead, sha)` writes `tl land` (the caller owns that verb); `store` is bd for the Dolt sync."""
    repo = str(Path(a.repo).resolve())
    beads, old = pairs(a.bead, "--bead"), pairs(a.supersede, "--supersede")
    items = [item_of(t, beads, old) for t in a.items]
    run = time.strftime("land-stack-%Y%m%d-%H%M%S")
    log = RunLog(real_stores(who.config).run_log(run), echo=None, run_id=run, host=socket.gethostname())
    cmds = Cmds(spawner, log, repo)
    lock = lock_path(who.config, git, repo)
    forge = Forge(cmds, git, repo, a.base, a.method)
    stack = Stack(forge, cmds, log, git, repo, lock, record, store.dolt_push, who.actor, who.session, a.wait_min)
    rc = stack.run(items)
    print(f"land-stack {'landed ' + str(len(items)) if rc == 0 else 'stopped, exit ' + str(rc)} (run {run})")
    return rc


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("land-stack", help="push, open, merge and record PRs, branches or a stack of them; stops at the first failure")
    p.add_argument("items", nargs="+", metavar="ITEM", help="a PR number or url, or a branch; lowest of the stack first")
    p.add_argument("--repo", default=".", metavar="DIR", help="the repo's checkout (default: the current directory)")
    p.add_argument("--base", default="main", help="the branch the PRs land on (default main)")
    p.add_argument("--method", choices=["squash", "merge", "rebase"], default="squash", help="how the forge merges (default squash)")
    p.add_argument("--bead", action="append", default=[], metavar="ITEM=BEAD", help="the bead to record the land on (task/<bead> names it)")
    p.add_argument("--supersede", action="append", default=[], metavar="ITEM=PR", help="an older PR to close once this item has merged")
    p.add_argument("--wait-min", type=float, default=None, help="give up (exit 75) after this long waiting for the land lock")
