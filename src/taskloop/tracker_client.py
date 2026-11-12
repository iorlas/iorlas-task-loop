"""Construct the real tracker client (beads_client `Bd`): the task read at an explicit tracker root, the round's reads,
the claim, fenced unclaim, heartbeat and the land's close, a hold's tracker writes (`TrackerHolds`), and the
process-wide drop of bd's location overrides. The one module that constructs a `Bd`. Wired by `composition` and
`cli_composition`."""

import os
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from beads_client import Bd, BdError, Runner

from taskloop.admit import Claim, Unclaim
from taskloop.claim_lease import BD_TIMEOUT_S, Beat, Heartbeat, HeartbeatFor
from taskloop.task import ReadyTitle, TaskBinding, TaskComment, TaskFacts, TaskInspection, TaskInspectionError, TaskScope
from taskloop.tracker import ACTOR, HELD, ReadyRows, gone, inspect_task, ready_titles, task_comments, task_facts, task_titles


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


def _reader(tracker_root: Path) -> Bd:
    return Bd(ACTOR, cwd=str(tracker_root))


def tracker_facts(task_id: str, tracker_root: Path) -> TaskFacts | None:
    """The task's facts (`Bd.show`); None when the tracker says it does not exist; a failed read raises TaskInspectionError."""
    return task_facts(_reader(tracker_root), task_id)


def tracker_comments(task_id: str, tracker_root: Path) -> tuple[TaskComment, ...]:
    """The task's comments, oldest first (`Bd.comments`); a failed read raises TaskInspectionError."""
    return task_comments(_reader(tracker_root), task_id)


def tracker_titles(task_ids: Sequence[str], tracker_root: Path) -> dict[str, str]:
    """Titles by id, one `Bd.show` per distinct id (bd has no batch show); unknown ids are omitted."""
    return task_titles(_reader(tracker_root), task_ids)


def tracker_ready_listing(label: str, tracker_root: Path) -> tuple[ReadyTitle, ...]:
    """What `bd ready` lists for `label`, in the tracker's order (unclaimed, unblocked)."""
    return ready_titles(_reader(tracker_root), label)


# The land's close (tl-8bh9.14.8 section 8): `closed` by this call, `already_closed` (found closed: never closed twice),
# `claim_lost` (another or no assignee, or bd's fence refused), `blocked` (bd refuses the close itself: open children or
# blockers, measured), `missing` (no such task), `unavailable` (bd could not be asked, or no answer in BD_TIMEOUT_S).
type Closed = Literal["closed", "already_closed", "claim_lost", "blocked", "missing", "unavailable"]
# bd 1.3.1's words when it refuses a close (measured in a scratch tracker, 2026-11-12): "cannot close <id>: 1 open child
# issue(s); close children first or use --force to override", "cannot close blocked issue: <id> is blocked by [<id>] (use
# --force to override)". Classified like `gone`: bd has no exit code for it.
REFUSED_CLOSE = "cannot close"


@dataclass(frozen=True)
class CloseAnswer:
    """The close's word; `assignee` as read for `claim_lost` (None: bd's fence refused, the holder unread); `detail` bd's
    own words for `blocked` and the failure's kind for `unavailable`."""

    word: Closed
    assignee: str | None = None
    detail: str = ""


type Close = Callable[[str, str, str], CloseAnswer]  # (tracker root, task id, reason)


@dataclass(frozen=True)
class TrackerClaims:
    """The tracker's write operations on a task's claim, each bound per tracker root: the claim, the fenced unclaim, the
    heartbeat, and the land's close."""

    claim: Claim
    unclaim: Unclaim
    heartbeat_for: HeartbeatFor
    close: Close


LOST = frozenset({"not_claimable", "precondition"})  # bd's words for a claim taken, reverted or closed
# bd 1.3.1 on an unclaim of a closed task, even one still assigned to the actor (measured 2026-11-12): exit 1, nothing
# written, the task not reopened; classified `other`. The unclaim maps it, and `gone`, to "not held" (tl-8bh9.14.9 5.3).
UNCLAIM_CLOSED = "cannot unclaim closed issue"
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
    return "lost" if error.kind in LOST or (error.kind == "other" and gone(error.text)) else "unrenewed"


def _closed(bd: Bd, task_id: str, reason: str) -> CloseAnswer:
    """One read (`Bd.show`): closed is `already_closed`, another or no assignee `claim_lost`; else `Bd.close` as this
    actor, fenced by a same-value assignee update (bd 1.3.1 refuses a close by an actor other than the assignee, and
    closing a closed task as its assignee changes nothing: measured). The claim is never returned: the close ends it."""
    try:
        found = bd.show(task_id)
        if found is None:
            return CloseAnswer("missing")
        if found.status == "closed":
            return CloseAnswer("already_closed")
        if found.assignee != ACTOR:
            return CloseAnswer("claim_lost", found.assignee)
        bd.close(task_id, reason, if_assignee=ACTOR)
    except BdError as error:
        return _close_failed(error)
    return CloseAnswer("closed")


def _close_failed(error: BdError) -> CloseAnswer:
    """A failed bd call of the close: the fence refused, the task deleted, bd's own refusal, or bd not answering."""
    if error.kind in LOST:
        return CloseAnswer("claim_lost")
    if error.kind == "other" and gone(error.text):
        return CloseAnswer("missing")
    if error.kind == "other" and REFUSED_CLOSE in error.text.lower():
        return CloseAnswer("blocked", detail=error.text)
    return CloseAnswer("unavailable", detail=error.kind)


def tracker_claims(run: Runner | None = None, client: type[Bd] = Bd) -> TrackerClaims:
    """`Bd.claim`, the compensating `Bd.unclaim` fenced to this actor (never forced; a closed or deleted task is not
    held: False), `Bd.heartbeat` mapped to a `Beat`
    (one bd call capped at BD_TIMEOUT_S, no lock retry: a refused beat is retried by the next interval), and the land's
    close (`_closed`, each of its bd calls capped at BD_TIMEOUT_S: a hung bd is `unavailable`). The one place a `Bd` is
    constructed for a write; `client` is the seam a test checks the construction through."""

    def located(tracker_root: str) -> str:
        return str(Path(tracker_root).expanduser().resolve())

    def bd(tracker_root: str) -> Bd:
        return client(ACTOR, cwd=located(tracker_root), run=run)

    def claim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).claim(task_id)

    def unclaim(tracker_root: str, task_id: str) -> bool:
        try:
            return bd(tracker_root).unclaim(task_id, if_assignee=ACTOR)
        except BdError as error:
            if error.kind == "other" and (gone(error.text) or UNCLAIM_CLOSED in error.text.lower()):
                return False  # nothing to return: the release records `not_held`
            raise

    def heartbeat_for(tracker_root: str, task_id: str) -> Heartbeat:
        renewing = client(ACTOR, cwd=located(tracker_root), run=run, timeout=BD_TIMEOUT_S, lock_retries=0)

        def beat() -> Beat:
            try:
                renewing.heartbeat(task_id)
            except BdError as error:
                return beat_of(error)
            return "held"

        return beat

    def close(tracker_root: str, task_id: str, reason: str) -> CloseAnswer:
        return _closed(client(ACTOR, cwd=located(tracker_root), run=run, timeout=BD_TIMEOUT_S), task_id, reason)

    return TrackerClaims(claim, unclaim, heartbeat_for, close)


# A hold's label step (tl-8bh9.14.9 5.2): `moved` (the approval label removed, `held` added), `absent` (`held` added, the
# label was not on the task), `not_ours` (another actor holds the task: nothing written), `closed`, `missing` (nothing
# written); `precondition` (the fence went stale: nothing written, retried) or `unavailable` (bd could not be asked);
# `bad_label` (the stored label is empty or starts with `-`, which bd would read as a flag: nothing asked).
type LabelStep = Literal["moved", "absent", "not_ours", "closed", "missing", "precondition", "unavailable", "bad_label"]
type HoldWrite = Literal["done", "missing", "unavailable"]  # a comment or the `held` label's removal


@dataclass(frozen=True)
class HoldAnswer[W: str]:
    """A hold write's word; `detail` the failure's kind for `unavailable`, and for `moved` and `absent` the assignee the
    label step read (`taskloop`, or empty: the claim had lapsed)."""

    word: W
    detail: str = ""


type Labels = Callable[[str, str, str], HoldAnswer[LabelStep]]  # (tracker root, task id, the stored approval label)
type Comment = Callable[[str, str, str], HoldAnswer[HoldWrite]]  # (tracker root, task id, text)
type Clear = Callable[[str, str], HoldAnswer[HoldWrite]]  # (tracker root, task id)


@dataclass(frozen=True)
class TrackerHolds:
    """A hold's tracker writes, each bound per tracker root and each bd call one try capped at BD_TIMEOUT_S (no lock
    retry, so no call outlasts `hold_store.COMMENT_LEASE`): the label step, the one comment, and the removal of `held`
    once the task is taken again."""

    labels: Labels
    comment: Comment
    clear: Clear


def _hold_failed[W: str](error: BdError, stale: W) -> HoldAnswer[W | Literal["missing", "unavailable"]]:
    if error.kind == "precondition":
        return HoldAnswer(stale)
    if error.kind == "other" and gone(error.text):
        return HoldAnswer("missing")
    return HoldAnswer("unavailable", error.kind)


def _labelled(bd: Bd, task_id: str, label: str) -> HoldAnswer[LabelStep]:
    """One read (`Bd.show`): missing, closed or another actor's task is written nothing; else, fenced on the assignee
    just read (the factory's own, or none), `held` added and then the approval label removed (both idempotent). A label
    bd would read as a flag is `bad_label` before any call."""
    if not label or label.startswith("-"):
        return HoldAnswer("bad_label")
    try:
        found = bd.show(task_id)
        if found is None:
            return HoldAnswer("missing")
        if found.status == "closed":
            return HoldAnswer("closed")
        if found.assignee not in (ACTOR, ""):
            return HoldAnswer("not_ours")
        bd.add_label(task_id, HELD, if_assignee=found.assignee)
        bd.remove_label(task_id, label)
    except BdError as error:
        return _hold_failed(error, "precondition")
    return HoldAnswer("moved" if label in found.labels else "absent", found.assignee)  # detail: the assignee read


def tracker_holds(run: Runner | None = None, client: type[Bd] = Bd) -> TrackerHolds:
    """`TrackerHolds` over `Bd` as this actor at the resolved tracker root, each call one try capped at BD_TIMEOUT_S (a
    hung bd is `unavailable`; no lock retry, as the heartbeat: a refused write is retried by the next round, and one
    call stays within `hold_store.COMMENT_LEASE`); `client` is the seam a test checks the construction through."""

    def bd(tracker_root: str) -> Bd:
        return client(ACTOR, cwd=str(Path(tracker_root).expanduser().resolve()), run=run, timeout=BD_TIMEOUT_S, lock_retries=0)

    def labels(tracker_root: str, task_id: str, label: str) -> HoldAnswer[LabelStep]:
        return _labelled(bd(tracker_root), task_id, label)

    def written(call: Callable[[], None]) -> HoldAnswer[HoldWrite]:
        try:
            call()
        except BdError as error:
            return _hold_failed(error, "unavailable")
        return HoldAnswer("done")

    def comment(tracker_root: str, task_id: str, text: str) -> HoldAnswer[HoldWrite]:
        return written(lambda: bd(tracker_root).comment(task_id, text))

    def clear(tracker_root: str, task_id: str) -> HoldAnswer[HoldWrite]:
        return written(lambda: bd(tracker_root).remove_label(task_id, HELD))

    return TrackerHolds(labels, comment, clear)
