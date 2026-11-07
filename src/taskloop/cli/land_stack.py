"""`tl land-stack ITEM...`: deliver existing PRs, branches or a stack of both, lowest first, as one run (app/land/stack.py)."""
import argparse
import socket
import time
from pathlib import Path

from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.finish import finish_run
from tlkernel.finish_projection import history
from tlkernel.forge import StackItem
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator

from taskloop.app.land.cmds import Cmds, Runs
from taskloop.app.land.forge import Forge
from taskloop.app.land.profile_change import owner_refusal
from taskloop.app.land.stack import MODE, Stack, lock_path
from taskloop.app.land.stackgate import StackGate
from taskloop.app.pipeline.finish import land_answer
from taskloop.app.slots.config import profile_slots
from taskloop.app.wire import closeguard
from taskloop.app.wire.slots import slot_of
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


def cmd_land_stack(a: argparse.Namespace, who: Identity, git: Git, spawner: Runs, store: Beads,
                   tl: list[str], *, env: Env | None = None) -> int:
    """`store` is bd (the land record and the Dolt sync); `tl` is the argv that runs tl itself (the gate runs `tl check` through it)."""
    env = env or Env()
    profile_change = a.profile_change
    if why := owner_refusal(profile_change, env):
        print(why)
        return 2
    repo = str(Path(a.repo).resolve())
    beads, old = pairs(a.bead, "--bead"), pairs(a.supersede, "--supersede")
    for flag, given in (("--bead", beads), ("--supersede", old)):
        for key in given:
            if key not in a.items:
                raise SystemExit(f"land-stack: {flag} {key}=... matches no item; the items given are: {', '.join(a.items)}")
    items = [item_of(t, beads, old) for t in a.items]
    locator = RunLocator(who.config)
    run = locator.create(repo, "", time.time(), mode=MODE, owner=who.actor, session=who.session).run  # the board finds a run through it
    stores = real_stores(who.config)
    log = RunLog(stores.run_log(run), echo=None, run_id=run, host=socket.gethostname())
    cmds = Cmds(spawner, log, repo, who.config.run_dir(run))
    lock = lock_path(who.config, git, repo)
    forge = Forge(cmds, git, repo, a.base, a.method)
    slot_repo = next((co.path for co in git.checkouts(repo) if co.main), repo)

    def landed(bead: str, sha: str) -> int:
        """`tl land` and its LANDED row (what `tl trace BEAD`, the board's landings and the close guard read): the one writer."""
        return closeguard.record_land(who, store, git, repo, f"origin/{a.base}", BeadId(bead), sha, f"{MODE}: merged as {sha[:12]}")

    stack = Stack(forge, cmds, log, git, repo, lock, landed, store.dolt_push, who.actor, who.session,
                  StackGate(cmds, git, stores, repo, f"origin/{a.base}", tl, env), store, a.wait_min,
                  lambda bead: locator.add_bead(run, bead),
                  lambda path: bool(slot_of(slot_repo, path, who, store, strict=True)), profile_slots(slot_repo).base,
                  cfg=who.config, profile_change=profile_change, jobs=a.jobs)
    rc = 1
    try:
        rc = stack.run(items)
    finally:  # every exit leaves a terminal state: done, or failed (a raise included)
        done = land_answer(time.time(), f"{len(items)} delivered" if rc == 0 else stack.failure_reason or f"exit {rc}",
                           sha=stack.last, ok=rc == 0)
        finish_run(who.config, run, done, lambda m, r: history(who.config, m, r, with_trace=False))
    if stack.failure_reason:
        print(f"land-stack: {stack.failure_reason}")
    print(f"land-stack {'landed ' + str(len(items)) if rc == 0 else 'stopped, exit ' + str(rc)} (run {run})")
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
