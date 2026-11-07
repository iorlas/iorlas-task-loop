"""Argument parser and shell bindings for `tl land-stack`."""
import argparse
import socket
from functools import partial

from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.finish import finish_run
from tlkernel.finish_projection import history
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlpipeline.api import land_answer
from tlslots.config import profile_slots

from taskloop.app.land.cmds import Runs
from taskloop.app.land.stack import item_of, pairs, run_stack
from taskloop.app.wire import closeguard, slotfx
from taskloop.app.wire.slots import slot_of
from taskloop.stores.runlog import RunLog

__all__ = ("add_parser", "cmd_land_stack", "item_of", "pairs")


def cmd_land_stack(a: argparse.Namespace, who: Identity, git: Git, spawner: Runs, store: Beads,
                   tl: list[str], *, env: Env | None = None) -> int:
    rc, lines = run_stack(a, who, git, spawner, store, tl, env=env, fx=slotfx.FX,
                         record=partial(closeguard.record_land, who, store, git),
                         slot=partial(slot_of, who=who, store=store, strict=True),
                         slot_base=lambda repo: profile_slots(repo).base,
                         runlog=lambda stores, run: RunLog(stores.run_log(run), echo=None, run_id=run, host=socket.gethostname()),
                         finish=lambda run, now, why, sha, ok: finish_run(
                             who.config, run, land_answer(now, why, sha=sha, ok=ok),
                             partial(history, who.config, with_trace=False)))
    for line in lines:
        print(line)
    return rc


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("land-stack", help="push, open, merge and record PRs, branches or a stack of them; stops at the first failure")
    p.add_argument("items", nargs="+", metavar="ITEM", help="a PR number or url, or a branch; lowest of the stack first")
    p.add_argument("--repo", default=".", metavar="DIR",
                   help="must be a checkout of the branch tree: the repo's hook gates the checked-out tree (default: current directory)")
    p.add_argument("--base", default="main", help="the branch the PRs land on (default main)")
    p.add_argument("--method", choices=["squash", "merge", "rebase"], default="squash", help="how the forge merges (default squash)")
    p.add_argument("--bead", action="append", default=[], metavar="ITEM=BEAD", help="the bead to record the land on (task/<bead> names it)")
    p.add_argument("--supersede", action="append", default=[], metavar="ITEM=PR", help="an older PR to close once this item has merged")
    p.add_argument("--wait-min", type=float, default=None, help="give up (exit 75) after this long waiting for the land lock")
    p.add_argument("--jobs", type=int, default=4, metavar="N",
                   help="gate up to N of the items at once before the one-by-one merges (default 4; 1 gates each in its turn)")
    p.add_argument("--profile-change", metavar="TEXT", help="owner's quoted approval and timestamp for this call's profile changes")
