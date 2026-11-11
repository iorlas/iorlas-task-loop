"""Construct the real tracker client (beads_client `Bd`): the task read at an explicit tracker root, the round's reads,
the claim, fenced unclaim and heartbeat, and the process-wide drop of bd's location overrides. The one module that
constructs a `Bd`. Wired by `composition`."""

import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

from beads_client import Bd, BdError, Runner

from taskloop.admit import Claim, Unclaim
from taskloop.claim_lease import BD_TIMEOUT_S, Beat, Heartbeat, HeartbeatFor
from taskloop.task import TaskBinding, TaskInspection, TaskInspectionError, TaskScope
from taskloop.tracker import ACTOR, ReadyRows, inspect_task


def _tracker_root(tracker_root: str) -> Path:
    """The explicit tracker root, resolved, without discovery; unusable is `invalid_binding`."""
    if not tracker_root.strip():
        raise TaskInspectionError("invalid_binding", "An explicit nonempty tracker root is required")
    try:
        root = Path(tracker_root).expanduser().resolve()
        if not root.is_dir():
            raise TaskInspectionError("invalid_binding", f"Tracker root is not an available directory: {root}")
    except (RuntimeError, OSError) as error:
        raise TaskInspectionError("invalid_binding", f"Cannot resolve tracker root: {tracker_root}") from error
    return root


def inspect_tracker_task(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    """Bind the supplied logical backlog to the explicit tracker root, without discovery."""
    scope = TaskScope(backlog)
    root = _tracker_root(tracker_root)
    return inspect_task(TaskBinding(scope, root), Bd(ACTOR, cwd=str(root)), task_id)


def tracker_reads(tracker_root: str) -> ReadyRows:
    """The scheduling round's tracker reads (ready set, parents) at the same root rule as `inspect_tracker_task`; raises
    TaskInspectionError(`invalid_binding`) for an unusable root. Only reads are reachable through the returned port."""
    return Bd(ACTOR, cwd=str(_tracker_root(tracker_root)))


@dataclass(frozen=True)
class TrackerClaims:
    """The tracker's three write operations on a task's claim, each bound per tracker root."""

    claim: Claim
    unclaim: Unclaim
    heartbeat_for: HeartbeatFor


LOST = frozenset({"not_claimable", "precondition"})  # bd's words for a claim taken, reverted or closed
GONE = "no issue found matching"  # bd 1.3.1 on a deleted bead (`resolving X: no issue found matching "X"`), classified `other`
# bd's tracker-location overrides (bd 1.3.1 binary strings). BEADS_DIR measured: it beats cwd, so bd would talk to another
# tracker than the stored root. BEADS_DB and BD_DB changed nothing in an embedded tracker (measured) and are dropped too.
BD_DISCOVERY = ("BEADS_DIR", "BEADS_DB", "BD_DB")


def tracker_located(environ: MutableMapping[str, str] = os.environ) -> None:
    """Drop bd's location overrides from this process's environment, which every bd child inherits, so the tracker root
    given as bd's cwd decides which tracker it talks to. Each process entry point (`tl`, the attempt entry) calls it first,
    before any thread or bd call: beads_client's runner takes no environment of its own."""
    for name in BD_DISCOVERY:
        environ.pop(name, None)


def beat_of(error: BdError) -> Beat:
    """A failed heartbeat: `lost` when bd says the claim is gone (taken, reverted, closed, or the bead deleted)."""
    return "lost" if error.kind in LOST or (error.kind == "other" and GONE in error.text) else "unrenewed"


def tracker_claims(run: Runner | None = None, client: type[Bd] = Bd) -> TrackerClaims:
    """`Bd.claim`, the compensating `Bd.unclaim` fenced to this actor (never forced), and `Bd.heartbeat` mapped to a `Beat`:
    one bd call capped at BD_TIMEOUT_S, no lock retry (a refused beat is retried by the next interval). The one place a
    `Bd` is constructed for a write; `client` is the seam a test checks the construction through."""

    def located(tracker_root: str) -> str:
        return str(Path(tracker_root).expanduser().resolve())

    def bd(tracker_root: str) -> Bd:
        return client(ACTOR, cwd=located(tracker_root), run=run)

    def claim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).claim(task_id)

    def unclaim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).unclaim(task_id, if_assignee=ACTOR)

    def heartbeat_for(tracker_root: str, task_id: str) -> Heartbeat:
        renewing = client(ACTOR, cwd=located(tracker_root), run=run, timeout=BD_TIMEOUT_S, lock_retries=0)

        def beat() -> Beat:
            try:
                renewing.heartbeat(task_id)
            except BdError as error:
                return beat_of(error)
            return "held"

        return beat

    return TrackerClaims(claim, unclaim, heartbeat_for)
