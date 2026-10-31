"""Record a direct push land and clean its task refs after verifying that they reached the base."""
import time

from taskloop.app.land import cleanup
from taskloop.app.wire import closeguard
from taskloop.app.wire.slots import load_cfg
from taskloop.contracts.enums import Outcome
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import Landed, LandedStore
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.log import Close, RunStart
from taskloop.contracts.ports import Beads, Git
from taskloop.contracts.run import RunState
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


def cmd_land(who: Identity, bead: BeadId, sha: str, store: Beads, git: Git, worktree: str | None = None,
             base: str | None = None) -> int:
    """The standalone verb is a direct land; PR delivery records through land-stack and never deletes a remote head."""
    where = worktree or "."
    base = base or load_cfg(where, git).base
    branch = "task/" + bead
    head = git.rev_parse(where, f"refs/heads/{branch}")
    remote_oid = cleanup.remote_oid(git, where, "origin", branch)
    full = git.rev_parse(where, sha + "^{commit}") or sha
    rc = closeguard.record_land(who, store, git, where, base, bead, full, f"tl land: {full[:12]} is on the base")
    if rc:
        return rc
    LandedStore(who.config).put(Landed(bead=bead, sha=full, base=base, t=time.time()))
    repo = next((co.path for co in git.checkouts(where) if co.main), where)
    locator = RunLocator(who.config)
    run = locator.create(repo, bead, time.time(), mode="stage:land", owner=who.actor, session=who.session).run
    log = RunLog(real_stores(who.config).run_log(run), run_id=run, bead=bead)
    log.emit(RunStart(worktree=where, branch=branch, mode="stage:land", owner=who.actor, session=who.session))
    # Direct pushes preserve ancestry. A newer task tip (local or remote) is not part of this receipt.
    checked_head = head if head and git.is_ancestor(where, head, full) else full
    checked_remote = remote_oid if remote_oid and git.is_ancestor(where, remote_oid, full) else ""
    prior = cleanup.previous(who.config, bead, repo, branch, full)
    row = cleanup.record(log, repo, branch, checked_head, full, "origin", checked_remote, prior)
    cleanup.retry(git, log, row)
    log.emit(Close(outcome=Outcome.LANDED, sha=full))
    locator.end(run, time.time(), RunState.DONE)
    return 0
