"""Record a direct push land and clean its task refs after verifying that they reached the base."""
import time

from tlkernel.beadsport import Beads
from tlkernel.branches import task_branch
from tlkernel.finish import finish_run
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.locator import RunLocator
from tlkernel.log import RunStart
from tlpipeline.api import land_answer
from tlslots.config import load_cfg, profile_slots

from taskloop.app.land import cleanup
from taskloop.app.wire import closeguard, slotfx
from taskloop.app.wire.slots import slot_of
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


def cmd_land(who: Identity, bead: BeadId, sha: str, store: Beads, git: Git, worktree: str | None = None,
             base: str | None = None) -> int:
    """The standalone verb is a direct land; PR delivery records through land-stack and never deletes a remote head."""
    where = worktree or "."
    base = base or load_cfg(where, git).base
    branch = task_branch(bead)
    head = git.rev_parse(where, f"refs/heads/{branch}")
    remote_oid = cleanup.remote_oid(git, where, "origin", branch)
    full = git.rev_parse(where, sha + "^{commit}") or sha
    repo = next((co.path for co in git.checkouts(where) if co.main), where)
    locator = RunLocator(who.config)
    run = locator.create(repo, bead, time.time(), mode="stage:land", owner=who.actor, session=who.session).run
    locator.worktree(run, where)
    log = RunLog(real_stores(who.config).run_log(run), run_id=run, bead=bead)
    log.emit(RunStart(worktree=where, branch=branch, mode="stage:land", owner=who.actor, session=who.session))
    rc = closeguard.record_land(who, store, git, where, base, bead, full, f"tl land: {full[:12]} is on the base", run=run)
    if rc:
        finish_run(who.config, run, land_answer(time.time(), "land was refused", ok=False))
        return rc
    # Direct pushes preserve ancestry. A newer task tip (local or remote) is not part of this receipt.
    checked_head = head if head and git.is_ancestor(where, head, full) else full
    checked_remote = remote_oid if remote_oid and git.is_ancestor(where, remote_oid, full) else ""
    prior = cleanup.previous(who.config, bead, repo, branch, full)
    row = cleanup.record(log, repo, branch, checked_head, full, "origin", checked_remote, prior)
    cleanup.retry(git, log, row, lambda path: bool(slot_of(repo, path, who, store, strict=True)), profile_slots(repo).base,
                  cfg=who.config, fx=slotfx.FX)
    finish_run(who.config, run, land_answer(time.time(), sha=full))
    return 0
