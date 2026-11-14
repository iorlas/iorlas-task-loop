"""Release's sole writer: prove processes stopped, reconcile stop facts, then park under custody and commit release.
Settled release keeps the claim; abandon returns it after commit. Unknown liveness and unsafe slots preserve custody.
No process is signalled and no work is reset. Process proof lives in release_proof; every external action is injected.
"""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import astuple, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from any_agent.procs import Worker
from beads_client import BdError
from git_porcelain import GitUnavailable
from stream_proc import OwnedProcess

from taskloop import wip
from taskloop.admit import Unclaim
from taskloop.agents.stop import reconcile
from taskloop.agents.stop_store import StopStore
from taskloop.attempt_reads import StoreRefused, StoreUnavailable, as_int, as_nullable_text, as_text
from taskloop.attempt_result import collect
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Observe, SlotFiles, WorkerGone
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import BLOCKED, ActionKind, Reason
from taskloop.factory_schema import RELEASE, SUCCESSOR, current, marks
from taskloop.ids import Ids
from taskloop.merge.store import MergeStore
from taskloop.prepare import task_branch
from taskloop.recovery.models import Intent
from taskloop.recovery.store import RecoveryStore
from taskloop.release_proof import NotReleased, Stopping, entry_stopped, recovery_stopped, setup_stopped, stop_proof, worker_stopped
from taskloop.setup_store import SetupSeen, running
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_park import Saver, park_slot, saver

__all__ = ["NotReleased", "Stopping", "entry_stopped", "setup_stopped", "stop_proof", "worker_stopped"]

type ParkHold = Callable[[str, str], AbstractContextManager[None]]  # (slot path, attempt id): the slot's lock, never waiting
type Scratch = Callable[[Path], bool]  # the slot's `.t/<slot>` emptied when it resolves where it belongs; False otherwise
type Claimed = Literal["kept", "unclaiming", "unclaimed", "not_held"]
CLAIMS: Final[tuple[Claimed, ...]] = ("kept", "unclaiming", "unclaimed", "not_held")
NOTHING: Final = "Nothing changed."
ROW: Final = """SELECT p.task_id,p.repo_id,p.slot,p.phase,p.rev,p.entry_pid,p.entry_start,p.entry_boot,p.worker_pid,p.worker_pgid,
p.worker_start,p.worker_boot,p.slot_head,p.tracker_root,
(SELECT s.path FROM reservation r JOIN slot s ON s.repo_id=r.repo_id AND s.name=r.slot
 WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id AND r.generation=p.generation),
""" + SUCCESSOR + """,x.claim,
EXISTS (SELECT 1 FROM execution e WHERE e.attempt_id=p.attempt_id),
EXISTS (SELECT 1 FROM task_hold h WHERE h.attempt_id=p.attempt_id)
FROM attempt p LEFT JOIN slot_release x ON x.attempt_id=p.attempt_id
WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=?"""
# Inside the write transaction: still the attempt the proof read (same rev and phase), still the task's current attempt,
# the reservation held at the key's generation, and no release row.
FENCE: Final = """SELECT 1 FROM attempt p WHERE p.attempt_id=? AND p.dispatch_token=? AND p.generation=? AND p.rev=? AND p.phase=?
AND NOT """ + SUCCESSOR + """
AND EXISTS (SELECT 1 FROM reservation r WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id
 AND r.generation=p.generation)
AND NOT EXISTS (SELECT 1 FROM slot_release x WHERE x.attempt_id=p.attempt_id)"""

# An abandon of a settled release, fenced again in its transaction: still `kept` and still the task's current attempt.
FLIP: Final = """UPDATE slot_release SET claim='unclaiming' WHERE attempt_id=? AND claim='kept'
AND NOT EXISTS (SELECT 1 FROM attempt p WHERE p.attempt_id=slot_release.attempt_id AND """ + SUCCESSOR + ")"


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


def free(con: sqlite3.Connection, repo_id: str, slot: str, attempt_id: str, generation: int) -> int:
    """The one deletion of a reservation, inside the caller's release transaction after its fenced record (an agent
    attempt's release row, a checks attempt's `check_store.record_release`, or a completed conflict release).
    Return the number removed so the caller can require exactly one deletion."""
    return con.execute("DELETE FROM reservation WHERE repo_id=? AND slot=? AND attempt_id=? AND generation=?",
                       (repo_id, slot, attempt_id, generation)).rowcount


@dataclass(frozen=True)
class _Row:
    key: AttemptKey
    task_id: str
    repo_id: str
    slot: str
    rev: int
    stopping: Stopping
    slot_head: str  # D
    tracker_root: str
    slot_path: str | None  # the held reservation's slot path; None when it is not held at the key's generation
    successor: bool  # `SUCCESSOR`: a later attempt of the task, or its unabandoned latest checks attempt; no longer current
    released: Claimed | None  # the claim of an existing release row: abandoned unless `kept`
    captured: bool
    held: bool
    setup: OwnedProcess | None = None  # the latest setup run's unsettled command (`SetupRow.unsettled`), if any
    reconciling: bool = False
    recovery: Intent | None = None


class ReconcileReason(StrEnum):
    HELD = "held"
    CAPTURED = "captured"
    INELIGIBLE = "ineligible"


def _reconcilable(row: _Row) -> NotReleased | None:
    reason = None
    if row.held:
        reason = ReconcileReason.HELD
    elif row.released == "kept" or (row.released is None and row.captured):
        reason = ReconcileReason.CAPTURED
    elif row.released is None and (row.stopping.phase not in ("dispatching", "registered") or row.stopping.entry is None):
        reason = ReconcileReason.INELIGIBLE
    return None if reason is None else NotReleased("refused", reason, f"The attempt is {reason}; its work stays reserved.")


def _claim(value: object) -> Claimed:
    found = next((claim for claim in CLAIMS if claim == value), None)
    if found is None:
        raise StoreUnavailable("Malformed release claim")
    return found


def _row(row: tuple[object, ...], key: AttemptKey) -> _Row:
    entry = None if any(value is None for value in row[5:8]) else (as_int(row[5]), as_text(row[6]), as_text(row[7]))
    worker = None if row[8] is None else Worker(pid=as_int(row[8]), pgid=as_int(row[9]), start=as_text(row[10]), boot=as_text(row[11]))
    released = None if row[16] is None else _claim(row[16])
    stopping = Stopping(as_text(row[3]), entry, worker)
    return _Row(key, as_text(row[0]), as_text(row[1]), as_text(row[2]), as_int(row[4]), stopping, as_text(row[12]), as_text(row[13]),
                as_nullable_text(row[14]), bool(as_int(row[15])), released, bool(as_int(row[17])), bool(as_int(row[18])))


@dataclass(frozen=True)
class SlotRelease:
    """`hold` is the slot's custody around the park and the transaction: `slot_lock.custody` for `tl step verify` and
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
        self, key: AttemptKey, abandon: bool, me: EntryIdentity | None, *, reconciling: bool = False,
    ) -> ReleaseResult:
        try:
            with operation(self.store, ActionKind.FINALIZE, ids=self.ids, subject=key.attempt_id,
                           existing=lambda owner: self.store.owns_entry(key, owner)):
                return self._release(key, abandon, me, reconciling=reconciling)
        except Fenced:
            return NotReleased("refused", Reason.DRAINING, BLOCKED)
        except Unobservable:
            return NotReleased("unavailable", "observe", "The calling process cannot be observed.")
        except (sqlite3.Error, StoreUnavailable):
            return NotReleased("unavailable", "store")

    def _release(
        self, key: AttemptKey, abandon: bool, me: EntryIdentity | None, *, reconciling: bool,
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

    def _returned(self, row: _Row, found: Released) -> Released | NotReleased:
        """An abandon after its commit: the claim returned; a failure names what was already done."""
        claim = self._unclaim(row)
        if not isinstance(claim, NotReleased):
            return replace(found, claim=claim)
        where = "no Git write" if found.parked is None else f"the slot parked at {found.parked}"
        return replace(claim, detail=f"{claim.detail} The reservation was removed, {where}.")

    @contextmanager
    def _writing(self) -> Generator[sqlite3.Connection]:
        con = self.store.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        with self.store.begin(con):
            yield con

    def _read(self, key: AttemptKey, con: sqlite3.Connection | None = None) -> _Row | None:
        """The release's own fenced read: `AttemptStore.load` refuses an admitted attempt that never registered its entry."""
        con = self.store.connect() if con is None else con
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        row: tuple[object, ...] | None = con.execute(ROW, astuple(key)).fetchone()
        if row is None:
            return None
        found = _row(row, key)
        recovery = None if found.released is not None else RecoveryStore(lambda: con, self.store.begin).release_intent(key)
        return replace(found, setup=running(con, key.attempt_id), recovery=recovery)

    def _refusal(self, row: _Row, abandon: bool, me: EntryIdentity | None) -> NotReleased | None:
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
        refused = (stop_proof(self.observe, self.gone, me, row.stopping) or setup_stopped(self.setup_seen, row.setup)
                   or self._merge_stopped(row))
        if refused is None and not reconcile(StopStore(self.store.connect, self.store.begin), row.key, self.gone, self.clock()):
            return NotReleased("unsettled", "worker_alive", "A recorded survivor may still run; the slot stays reserved.")
        return refused

    def _merge_stopped(self, row: _Row) -> NotReleased | None:
        work = MergeStore(self.store.connect, self.store.begin).get(row.key.attempt_id)
        if work is not None:
            for execution in work.executions:
                process = execution.worker
                if process is not None and not self.gone(Worker(pid=process.pid, pgid=process.pgid,
                                                               start=process.start, boot=process.boot)):
                    return NotReleased("unsettled", "worker_alive", "A merge resolution process may still run; the slot stays reserved.")
        return None

    def _pending(self, row: _Row, abandon: bool) -> ReleaseResult:
        """Released before: only what is pending is finished, with no Git and no lock. Abandoning a settled release flips
        it, then returns the claim; an `unclaiming` claim is retried."""
        claim = row.released or "kept"
        if abandon and claim == "kept" and row.successor:  # the claim is the later attempt's now (a next step holds it)
            current = "A later attempt or a checks attempt of the task is current: release that one first."
            return NotReleased("refused", "changed", f"{current} {NOTHING}")
        if abandon and claim == "kept":
            with self._writing() as con:
                flipped = con.execute(FLIP, (row.key.attempt_id,)).rowcount
            if flipped != 1:
                return NotReleased("unavailable", "changed", f"Another release changed it first. {NOTHING}")
            claim = "unclaiming"
        if claim != "unclaiming":
            return AlreadyReleased(row.slot, claim, claim != "kept")
        found = self._unclaim(row)
        return found if isinstance(found, NotReleased) else Released(row.slot, None, False, found, True)

    def _held(self, row: _Row, abandon: bool) -> Released | NotReleased:
        slot_path = row.slot_path or ""
        try:
            with self.hold(slot_path, row.key.attempt_id):
                return self._parked(row, Path(slot_path), abandon)
        except SlotBusy:
            return NotReleased("unavailable", "slot_busy", f"Another entry, verify or release holds the slot. {NOTHING}")
        except SlotLockUnavailable:
            return NotReleased("unavailable", "lock", f"The slot's lock file cannot be opened. {NOTHING}")

    def _custody_proof(self, row: _Row) -> NotReleased | None:
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

    def _parked(self, row: _Row, path: Path, abandon: bool) -> Released | NotReleased:
        """Under the lock: the slot read and its park, then the transaction."""
        refused = self._custody_proof(row)
        if refused is not None:
            return refused
        try:
            slot = park_slot(self.checkouts, self.slot_files, path, row.repo_id, row.slot_head, task_branch(row.task_id),
                             self._saver(row, abandon))
        except GitUnavailable as error:
            return NotReleased("unavailable", "git", f"Git could not read or park the slot ({type(error).__name__}: {error}): "
                               "it may be half checked out; inspect it, then rerun. Nothing was recorded.")
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

    def _saver(self, row: _Row, abandon: bool) -> Saver | None:
        """The save of a hold's abandon (only an attempt that has a hold saves; a person's release keeps its refusals)."""
        log = self.saved
        if not abandon or log is None or not log.held(row.key.attempt_id):
            return None
        work = MergeStore(self.store.connect, self.store.begin).get(row.key.attempt_id)
        inputs = None if work is None or work.target is None else (work.source, work.target)
        source = wip.Source(row.task_id, row.key.attempt_id, row.slot, row.slot_head, inputs)

        return saver(log, self.slot_files, self.clock, source)

    def _record(self, row: _Row, head: str, abandon: bool) -> bool:
        """One write transaction, fenced on what the proof read: the release row in, the reservation out."""
        key = row.key
        with self._writing() as con:
            if self._read(key, con) != replace(row, reconciling=False):
                return False
            if con.execute(FENCE, (*astuple(key), row.rev, row.stopping.phase)).fetchone() is None:
                return False
            values = (*astuple(key), head, self.clock(), "unclaiming" if abandon else "kept")
            con.execute(f"INSERT INTO slot_release ({RELEASE}) VALUES ({marks(RELEASE)})", values)
            free(con, row.repo_id, row.slot, key.attempt_id, key.reservation_generation)
        return True

    def _unclaim(self, row: _Row) -> Literal["unclaimed", "not_held"] | NotReleased:
        """After the commit and outside the lock: the claim back to the tracker at the stored root, fenced to this actor
        (never forced); its answer recorded. A tracker failure leaves `unclaiming` for the next call."""
        try:
            back = self.unclaim(row.tracker_root, row.task_id)
        except BdError as error:
            return NotReleased("unavailable", "tracker", f"Released; the tracker claim is still to be returned ({error.kind}). "
                               "The claim return remains pending for reconciliation.")
        claim: Literal["unclaimed", "not_held"] = "unclaimed" if back else "not_held"
        try:
            with self._writing() as con:
                con.execute("UPDATE slot_release SET claim=? WHERE attempt_id=? AND claim='unclaiming'", (claim, row.key.attempt_id))
        except (sqlite3.Error, StoreUnavailable) as error:
            unrecorded = f"Released and the claim {claim}, but that was not recorded ({type(error).__name__}): rerun."
            return NotReleased("unavailable", "store", unrecorded)
        return claim
