"""Prove processes stopped, reconcile stop facts, then park under custody and commit release through its store.
Settled release keeps the claim; abandon returns it after commit. Unknown liveness and unsafe slots preserve custody.
No process is signalled and no work is reset. Process proof lives in release_proof; every external action is injected.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from any_agent.procs import Worker
from beads_client import BdError
from git_porcelain import GitUnavailable

from taskloop import wip
from taskloop.admit import Unclaim
from taskloop.agents.stop import reconcile
from taskloop.agents.stop_store import StopStore
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_result import collect
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Observe, SlotFiles, WorkerGone
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import BLOCKED, ActionKind, Reason
from taskloop.ids import Ids
from taskloop.merge.store import MergeStore
from taskloop.prepare import task_branch
from taskloop.release_proof import NotReleased, Stopping, entry_stopped, recovery_stopped, setup_stopped, stop_proof, worker_stopped
from taskloop.setup_store import SetupSeen
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_park import Saver, park_slot, saver
from taskloop.slot_release_store import Claimed, ReleaseRow, SlotReleaseStore

__all__ = ["NotReleased", "Stopping", "entry_stopped", "setup_stopped", "stop_proof", "worker_stopped"]

type ParkHold = Callable[[str, str], AbstractContextManager[None]]  # (slot path, attempt id): the slot's lock, never waiting
type Scratch = Callable[[Path], bool]  # the slot's `.t/<slot>` emptied when it resolves where it belongs; False otherwise
NOTHING: Final = "Nothing changed."


@dataclass(frozen=True)
class Released:
    """The park commit (None without a Git write), reservation removal, claim and whether this was an abandon."""

    slot: str
    parked: str | None
    reservation_removed: bool
    claim: Literal["kept", "unclaimed", "not_held"]
    abandoned: bool


@dataclass(frozen=True)
class AlreadyReleased:
    """Released before and nothing pending: nothing changed."""

    slot: str
    claim: Claimed
    abandoned: bool


type ReleaseResult = Released | AlreadyReleased | NotReleased


RELEASED_WORDS: Final = ("released", "already_released")


def is_released(word: str) -> bool:
    """Whether a `release_word` (or a log's `release=` word) says the slot is free."""
    return word in RELEASED_WORDS


def release_word(result: ReleaseResult) -> str:
    """One word for release progress: released, already_released, held, refused or unavailable with its reason."""
    if not isinstance(result, NotReleased):
        return "released" if isinstance(result, Released) else "already_released"
    if result.kind == "unsettled" or (result.kind == "refused" and result.reason.startswith("slot_")):
        return "held:" + result.reason
    return result.word


class ReconcileReason(StrEnum):
    HELD = "held"
    CAPTURED = "captured"
    INELIGIBLE = "ineligible"


def _reconcilable(row: ReleaseRow) -> NotReleased | None:
    reason = None
    if row.held:
        reason = ReconcileReason.HELD
    elif row.released == "kept" or (row.released is None and row.captured):
        reason = ReconcileReason.CAPTURED
    elif row.released is None and (row.stopping.phase not in ("dispatching", "registered") or row.stopping.entry is None):
        reason = ReconcileReason.INELIGIBLE
    return None if reason is None else NotReleased("refused", reason, f"The attempt is {reason}; its work stays reserved.")


@dataclass(frozen=True)
class SlotRelease:
    """`hold` is the slot's custody around the park and the transaction: `slot_lock.custody` for `tl step commit` and
    `tl step release`, a no-op for the entry, which holds the lock already."""

    store: AttemptStore
    checkouts: Checkouts
    slot_files: SlotFiles
    observe: Observe
    gone: WorkerGone
    hold: ParkHold
    unclaim: Unclaim
    clock: Callable[[], float]
    setup_seen: SetupSeen
    scratch: Scratch  # empties the slot's `.t/<slot>` after a release (`RealEnvFiles.empty_scratch`)
    ids: Ids = field(kw_only=True)
    saved: wip.SavedLog | None = None  # the hold's record of saved commits: an abandon of a held attempt saves a dirty slot first

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        return self._run_release(key, abandon, me)

    def reconcile(self, key: AttemptKey) -> ReleaseResult:
        """Release uncaptured lost-entry work, or finish its already recorded claim return."""
        return self._run_release(key, True, None, reconciling=True)

    def _run_release(
        self,
        key: AttemptKey,
        abandon: bool,
        me: EntryIdentity | None,
        *,
        reconciling: bool = False,
    ) -> ReleaseResult:
        try:
            with operation(
                self.store,
                ActionKind.FINALIZE,
                ids=self.ids,
                subject=key.attempt_id,
                existing=lambda owner: self.store.owns_entry(key, owner),
            ):
                return self._release(key, abandon, me, reconciling=reconciling)
        except Fenced:
            return NotReleased("refused", Reason.DRAINING, BLOCKED)
        except Unobservable:
            return NotReleased("unavailable", "observe", "The calling process cannot be observed.")
        except sqlite3.Error, StoreUnavailable:
            return NotReleased("unavailable", "store")

    def _release(
        self,
        key: AttemptKey,
        abandon: bool,
        me: EntryIdentity | None,
        *,
        reconciling: bool,
    ) -> ReleaseResult:
        """Release the attempt's reservation (settled) or abandon it; `me` is the calling entry's own identity."""
        try:
            row = self._read(key)
            if row is None:
                return NotReleased("refused", "absent", f"No such attempt. {NOTHING}")
            row = replace(row, reconciling=reconciling)
            refused = _reconcilable(row) if reconciling else None
            if refused is not None:
                return refused
            if row.released is not None:
                return self._pending(row, abandon)
            refused = self._refusal(row, abandon, me)
            if refused is not None:
                return refused
        except (sqlite3.Error, StoreUnavailable, StoreRefused) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {NOTHING}")
        found = self._held(row, abandon)
        return self._returned(row, found) if abandon and isinstance(found, Released) else found

    def _returned(self, row: ReleaseRow, found: Released) -> Released | NotReleased:
        """An abandon after its commit: the claim returned; a failure names what was already done."""
        claim = self._unclaim(row)
        if not isinstance(claim, NotReleased):
            return replace(found, claim=claim)
        where = "no Git write" if found.parked is None else f"the slot parked at {found.parked}"
        return replace(claim, detail=f"{claim.detail} The reservation was removed, {where}.")

    @property
    def _releases(self) -> SlotReleaseStore:
        return SlotReleaseStore(self.store.connect, self.store.begin)

    def _read(self, key: AttemptKey) -> ReleaseRow | None:
        return self._releases.read(key)

    def _refusal(self, row: ReleaseRow, abandon: bool, me: EntryIdentity | None) -> NotReleased | None:
        """Read before anything changes: the reservation held, the result collected (settled only), the stop proof."""
        if row.slot_path is None or row.successor:
            return NotReleased("unavailable", "changed", f"The attempt no longer holds its reservation. {NOTHING}")
        recovery = recovery_stopped(self.setup_seen, row.recovery)
        if recovery is not None:
            return recovery
        if not abandon:
            result = collect(self.store, row.key)
            if result.status == "unavailable":
                return NotReleased("unavailable", "store", f"The result could not be read. {NOTHING}")
            if result.status != "collected":
                return NotReleased("refused", "not_terminal", f"The step has not ended: finish it, repeat it, or abandon it. {NOTHING}")
        refused = (
            stop_proof(self.observe, self.gone, me, row.stopping) or setup_stopped(self.setup_seen, row.setup) or self._merge_stopped(row)
        )
        if refused is None and not reconcile(StopStore(self.store.connect, self.store.begin), row.key, self.gone, self.clock()):
            return NotReleased("unsettled", "worker_alive", "A recorded survivor may still run; the slot stays reserved.")
        return refused

    def _merge_stopped(self, row: ReleaseRow) -> NotReleased | None:
        work = MergeStore(self.store.connect, self.store.begin).get(row.key.attempt_id)
        if work is not None:
            for execution in work.executions:
                process = execution.worker
                if process is not None and not self.gone(
                    Worker(pid=process.pid, pgid=process.pgid, start=process.start, boot=process.boot)
                ):
                    return NotReleased("unsettled", "worker_alive", "A merge resolution process may still run; the slot stays reserved.")
        return None

    def _pending(self, row: ReleaseRow, abandon: bool) -> ReleaseResult:
        """Released before: only what is pending is finished, with no Git and no lock. Abandoning a settled release flips
        it, then returns the claim; an `unclaiming` claim is retried."""
        claim = row.released or "kept"
        if abandon and claim == "kept" and row.successor:  # the claim is the later attempt's now (a next step holds it)
            current = "A later attempt or a checks attempt of the task is current: release that one first."
            return NotReleased("refused", "changed", f"{current} {NOTHING}")
        if abandon and claim == "kept":
            flipped = self._releases.flip(row.key.attempt_id)
            if flipped != 1:
                return NotReleased("unavailable", "changed", f"Another release changed it first. {NOTHING}")
            claim = "unclaiming"
        if claim != "unclaiming":
            return AlreadyReleased(row.slot, claim, claim != "kept")
        found = self._unclaim(row)
        return found if isinstance(found, NotReleased) else Released(row.slot, None, False, found, True)

    def _held(self, row: ReleaseRow, abandon: bool) -> Released | NotReleased:
        slot_path = row.slot_path or ""
        try:
            with self.hold(slot_path, row.key.attempt_id):
                return self._parked(row, Path(slot_path), abandon)
        except SlotBusy:
            return NotReleased("unavailable", "slot_busy", f"Another entry, factory commit or release holds the slot. {NOTHING}")
        except SlotLockUnavailable:
            return NotReleased("unavailable", "lock", f"The slot's lock file cannot be opened. {NOTHING}")

    def _custody_proof(self, row: ReleaseRow) -> NotReleased | None:
        """Reread and observe under custody, outside any write transaction, then compare."""
        expected = replace(row, reconciling=False)
        if self._read(row.key) != expected:
            return NotReleased("unavailable", "changed", "The attempt changed after the stop proof. Nothing changed.")
        refused = recovery_stopped(self.setup_seen, row.recovery)
        if refused is not None:
            return refused
        if self._read(row.key) != expected:
            return NotReleased("unavailable", "changed", "Recovery facts changed after observation. Nothing changed.")
        return None

    def _parked(self, row: ReleaseRow, path: Path, abandon: bool) -> Released | NotReleased:
        """Under the lock: the slot read and its park, then the transaction."""
        refused = self._custody_proof(row)
        if refused is not None:
            return refused
        try:
            slot = park_slot(
                self.checkouts, self.slot_files, path, row.repo_id, row.slot_head, task_branch(row.task_id), self._saver(row, abandon)
            )
        except GitUnavailable as error:
            return NotReleased(
                "unavailable",
                "git",
                f"Git could not read or park the slot ({type(error).__name__}: {error}): "
                "it may be half checked out; inspect it, then rerun. Nothing was recorded.",
            )
        if isinstance(slot, NotReleased):
            return slot
        head, parked = slot
        where = "No Git write" if parked is None else f"The slot was parked at {parked}"
        try:
            recorded = self._record(row, head, abandon)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {where}; nothing was recorded.")
        if not recorded:
            return NotReleased("unavailable", "changed", f"The attempt changed after the stop proof. {where}; nothing was recorded.")
        self.scratch(path)  # best effort: the next preparation empties it again before any agent
        return Released(row.slot, parked, True, "kept", abandon)

    def _saver(self, row: ReleaseRow, abandon: bool) -> Saver | None:
        """The save of a hold's abandon (only an attempt that has a hold saves; a person's release keeps its refusals)."""
        log = self.saved
        if not abandon or log is None or not log.held(row.key.attempt_id):
            return None
        work = MergeStore(self.store.connect, self.store.begin).get(row.key.attempt_id)
        inputs = None if work is None or work.target is None else (work.source, work.target)
        source = wip.Source(row.task_id, row.key.attempt_id, row.slot, row.slot_head, inputs)

        return saver(log, self.slot_files, self.clock, source)

    def _record(self, row: ReleaseRow, head: str, abandon: bool) -> bool:
        """One write transaction, fenced on what the proof read: the release row in, the reservation out."""
        return self._releases.record_release(row, head, self.clock(), abandon)

    def _unclaim(self, row: ReleaseRow) -> Literal["unclaimed", "not_held"] | NotReleased:
        """After the commit and outside the lock: the claim back to the tracker at the stored root, fenced to this actor
        (never forced); its answer recorded. A tracker failure leaves `unclaiming` for the next call."""
        try:
            back = self.unclaim(row.tracker_root, row.task_id)
        except BdError as error:
            return NotReleased(
                "unavailable",
                "tracker",
                f"Released; the tracker claim is still to be returned ({error.kind}). The claim return remains pending for reconciliation.",
            )
        claim: Literal["unclaimed", "not_held"] = "unclaimed" if back else "not_held"
        try:
            self._releases.complete(row.key.attempt_id, claim)
        except (sqlite3.Error, StoreUnavailable) as error:
            unrecorded = f"Released and the claim {claim}, but that was not recorded ({type(error).__name__}): rerun."
            return NotReleased("unavailable", "store", unrecorded)
        return claim
