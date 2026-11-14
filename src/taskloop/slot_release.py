"""Release a slot reservation (a lease), and abandon an attempt: the one writer of `slot_release` and the only deleter of
a `reservation` (`free`, also called by the checks release, `check_release`); its one Git write is `park`, under the
slot's lock (`park_slot`, shared with the checks release).

Two modes of one operation. settled: the attempt's result is collected; the slot is parked at the attempt's admission
base D and the tracker claim is kept (a verified plan is not task completion; land is). abandon: any phase; the slot is
parked, the claim returned (the fenced `unclaim`, never forced) and the attempt thrown away, so the task can be started
again. Before anything changes, in order: the terminal check (settled only), the stop proof (the registered entry, then
the agent and its group, then the latest setup run's unsettled command and its group, boot-aware: `unsettled
setup_running`, `unavailable setup_unknown`), then the
slot's lock (`hold`, never waiting), the slot read and the park, then one write transaction fenced on the attempt, its
reservation and the `rev` and phase read at proof time: the release row in, the reservation out; then, still under the
lock and after the stop proof, the slot's scratch (`TMPDIR`, `.t/<slot>`) emptied, best effort. An abandon unclaims
after that commit; a failed unclaim stays `unclaiming` for the next call to retry. A slot that is dirty, on another
branch, redirected or unborn is refused and stays reserved: release never resets work.

Everything is injected: the store, the Git views, the slot file port, the entry and worker observations, the lock, the
tracker's unclaim, the clock, the setup observation and the scratch's emptying. It imports neither `operations` nor
`repeat` (the entry's import closure).
"""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import astuple, dataclass, field, replace
from pathlib import Path
from typing import Final, Literal

from any_agent.procs import Worker
from beads_client import BdError
from git_porcelain import GitUnavailable, Repo, Worktree
from stream_proc import OwnedProcess

from taskloop import wip
from taskloop.admit import Unclaim
from taskloop.attempt_reads import StoreUnavailable, as_int, as_nullable_text, as_text
from taskloop.attempt_result import collect
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Observe, SlotFiles, WorkerGone
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import BLOCKED, ActionKind, Reason
from taskloop.factory_schema import RELEASE, SUCCESSOR, current, marks
from taskloop.ids import Ids
from taskloop.merge.store import MergeStore
from taskloop.prepare import task_branch
from taskloop.setup_store import SetupSeen, running
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_state import SlotState, listing, observe_slot

type ParkHold = Callable[[str, str], AbstractContextManager[None]]  # (slot path, attempt id): the slot's lock, never waiting
type Scratch = Callable[[Path], bool]  # the slot's `.t/<slot>` emptied when it resolves where it belongs; False otherwise
type Claimed = Literal["kept", "unclaiming", "unclaimed", "not_held"]
CLAIMS: Final[tuple[Claimed, ...]] = ("kept", "unclaiming", "unclaimed", "not_held")
NOTHING: Final = "Nothing changed."
ROW: Final = """SELECT p.task_id,p.repo_id,p.slot,p.phase,p.rev,p.entry_pid,p.entry_start,p.entry_boot,p.worker_pid,p.worker_pgid,
p.worker_start,p.worker_boot,p.slot_head,p.tracker_root,
(SELECT s.path FROM reservation r JOIN slot s ON s.repo_id=r.repo_id AND s.name=r.slot
 WHERE r.repo_id=p.repo_id AND r.slot=p.slot AND r.attempt_id=p.attempt_id AND r.generation=p.generation),
""" + SUCCESSOR + """,x.claim
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
    """Exactly what this call changed: `parked`, the commit it parked the slot at (None: no Git write); whether it
    removed the reservation; the claim (`kept` when settled); whether the attempt is now abandoned."""

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


@dataclass(frozen=True)
class NotReleased:
    """A refusal (exit 1), or an unknown or unsettled observation (exit 3, rerun); `detail` says what changed."""

    kind: Literal["refused", "unavailable", "unsettled"]
    reason: str
    detail: str = NOTHING

    @property
    def word(self) -> str:
        return f"{self.kind}:{self.reason}"


type ReleaseResult = Released | AlreadyReleased | NotReleased


RELEASED_WORDS: Final = ("released", "already_released")


def is_released(word: str) -> bool:
    """Whether a `release_word` (or a log's `release=` word) says the slot is free."""
    return word in RELEASED_WORDS


def release_word(result: ReleaseResult) -> str:
    """The one word for a log line, a status or a result: `released` (this call), `already_released` (nothing pending),
    `held:<reason>` (the slot's state or a live process keeps it reserved), `refused:<reason>` or `unavailable:<reason>`."""
    if not isinstance(result, NotReleased):
        return "released" if isinstance(result, Released) else "already_released"
    if result.kind == "unsettled" or (result.kind == "refused" and result.reason.startswith("slot_")):
        return "held:" + result.reason
    return result.word


@dataclass(frozen=True)
class Stopping:
    """What the stop proof reads of an attempt: its phase, its registered entry and its registered agent."""

    phase: str
    entry: EntryIdentity | None
    worker: Worker | None


def entry_stopped(
    observe: Observe, me: EntryIdentity | None, entry: EntryIdentity | None, process: str | None = None,
) -> NotReleased | None:
    """The registered entry, by its boot-aware identity (a native process-table read, never by name): running refuses
    unless it is `me` (the entry releasing itself after its own verify); unknown is unavailable; gone, a different process
    or no registered entry passes. `process` names it in the detail (a land candidate's `land process`)."""
    if entry is None or entry == me:
        return None
    seen = observe(entry)
    if seen == "matching":
        running = f"The {process or "attempt's entry"} runs as pid {entry[0]}: wait, or stop it by verified pid. {NOTHING}"
        return NotReleased("refused", "entry_running", running)
    unknown = f"The {process or 'registered entry'} could not be observed. {NOTHING}"
    return NotReleased("unavailable", "observe", unknown) if seen == "unknown" else None


def worker_stopped(gone: WorkerGone, phase: str, worker: Worker | None) -> NotReleased | None:
    """The registered agent: gone (or another process) with no process left in its group; unknown counts as alive. With no
    agent recorded only `admitted` passes: the dispatch write precedes the spawn, so from `dispatching` on an agent may
    run with no recorded identity."""
    if worker is None:
        unknown = "Dispatched with no agent recorded: it cannot be shown stopped; the whole-DB discard is the only way out."
        return None if phase == "admitted" else NotReleased("unsettled", "worker_unknown", f"{unknown} {NOTHING}")
    alive = f"The agent (pid {worker.pid}, process group {worker.pgid}) or its group may run: stop it by verified pid. {NOTHING}"
    return None if gone(worker) else NotReleased("unsettled", "worker_alive", alive)


def stop_proof(observe: Observe, gone: WorkerGone, me: EntryIdentity | None, row: Stopping) -> NotReleased | None:
    """The one stop rule, shared with a repeat: exactly the entry observation, then the agent's. The slot's lock is never
    part of it (a free lock is not a stopped agent)."""
    return entry_stopped(observe, me, row.entry) or worker_stopped(gone, row.phase, row.worker)


def setup_stopped(seen: SetupSeen, setup: OwnedProcess | None) -> NotReleased | None:
    """The latest setup run's unsettled command, by the entry's rule (`setup_seen`): gone with an empty group, or from
    another boot, passes; alive refuses; unknown is unavailable. The release never stops it (the factory signals
    nothing); the person waits, or stops the group once its members are shown to be the slot's setup. Shared with the
    checks release."""
    found = "gone" if setup is None else seen(setup)
    if setup is None or found == "gone":
        return None
    if found == "unknown":
        return NotReleased("unavailable", "setup_unknown", f"The slot's setup could not be observed. {NOTHING}")
    alive = f"The slot's setup (process group {setup.pgid}, recorded this boot) still runs: wait, or see the guide. {NOTHING}"
    return NotReleased("unsettled", "setup_running", alive)


type Saver = Callable[[Repo, Worktree, SlotState], wip.Refused | None]  # a hold's save of the slot's work, under the lock


def park_slot(
    checkouts: Checkouts, slot_files: SlotFiles, path: Path, repo_id: str, slot_head: str, branch: str | None,
    save: Saver | None = None,
) -> tuple[str, str | None] | NotReleased:
    """The release's one Git write, shared with the checks release (under the slot's lock): the slot on its own hardened
    view, the pointer first (`redirected` makes no Git call); on exactly `branch` (the implement attempt's `task/<id>`;
    None for a checks slot, which is only ever detached) and clean it is parked at D (the branch keeps its tip);
    detached and clean it is left where it is (never prepared, or parked by an earlier call that died before its
    transaction) when it is at D, else parked at D. Dirty, on another branch, redirected or unborn refuses: it never
    resets work. Returns where the slot is left and the park."""
    state = observe_slot(checkouts, slot_files, str(path), repo_id)
    if isinstance(state, str) or state.head is None:
        return _unreadable(state)
    if save is not None and state.branch in (None, branch):
        return _saved(checkouts, path, state, slot_head, save)
    if state.dirty:
        left = listing(checkouts(path, git_dir=state.gitdir), path)
        again = f"List them again with `git -C {path} status --short`; remove or restore each, then run it again. {NOTHING}"
        return NotReleased("refused", "slot_dirty", "\n".join([*left, again]))
    merging = checkouts(path, git_dir=state.gitdir).worktree(path).merging()
    if state.branch is None and state.head == slot_head and not merging:
        return state.head, None
    if merging or state.branch not in (None, branch):
        return (NotReleased("unavailable", "merge_pending", "An active merge needs owning preservation before the slot can be parked.")
                if merging else NotReleased("refused", "slot_branch", f"The slot is on another branch. {NOTHING}"))
    return slot_head, str(checkouts(path, git_dir=state.gitdir).worktree(path).park(slot_head))


def _unreadable(state: SlotState | str) -> NotReleased:
    """The refusal of a slot that cannot be read (a word) or has no commit."""
    if isinstance(state, str):
        reason = "slot_redirected" if state == "redirected" else state
        return NotReleased("refused" if state == "redirected" else "unavailable", reason, f"Inspect the slot. {NOTHING}")
    return NotReleased("refused", "slot_unborn", f"The slot has no commit. {NOTHING}")


def _saved(checkouts: Checkouts, path: Path, state: SlotState, slot_head: str, save: Saver) -> tuple[str, str | None] | NotReleased:
    """A hold's park: the slot's work saved on the task branch first (`wip.save`), then detached at D with its ignored files
    kept; a slot already at D, clean, is left as it is."""
    view = checkouts(path, git_dir=state.gitdir)
    slot = view.worktree(path)
    if state.dirty or state.branch is not None or state.head != slot_head or slot.merging():
        refused = save(view, slot, state)
        if refused is not None:
            return NotReleased("unavailable", refused.reason.value, refused.detail)
    parked = wip.park(slot, slot_head)
    if isinstance(parked, wip.Refused):
        return NotReleased("unavailable", parked.reason.value, parked.detail)
    return slot_head, parked


def free(con: sqlite3.Connection, repo_id: str, slot: str, attempt_id: str, generation: int) -> None:
    """The one deletion of a reservation, inside the caller's release transaction after its fenced record (an agent
    attempt's release row, or a checks attempt's `check_store.record_release`)."""
    con.execute("DELETE FROM reservation WHERE repo_id=? AND slot=? AND attempt_id=? AND generation=?",
                (repo_id, slot, attempt_id, generation))


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
    setup: OwnedProcess | None = None  # the latest setup run's unsettled command (`SetupRow.unsettled`), if any


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
                as_nullable_text(row[14]), bool(as_int(row[15])), released)


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
        try:
            with operation(self.store, ActionKind.FINALIZE, ids=self.ids, subject=key.attempt_id,
                           existing=lambda owner: self.store.owns_entry(key, owner)):
                return self._release(key, abandon, me)
        except Fenced:
            return NotReleased("refused", Reason.DRAINING, BLOCKED)
        except Unobservable:
            return NotReleased("unavailable", "observe", "The calling process cannot be observed.")
        except (sqlite3.Error, StoreUnavailable):
            return NotReleased("unavailable", "store")

    def _release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        """Release the attempt's reservation (settled) or abandon it; `me` is the calling entry's own identity."""
        try:
            row = self._read(key)
            if row is None:
                return NotReleased("refused", "absent", f"No such attempt. {NOTHING}")
            if row.released is not None:
                return self._pending(row, abandon)
            refused = self._refusal(row, abandon, me)
            if refused is not None:
                return refused
        except (sqlite3.Error, StoreUnavailable) as error:
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

    def _read(self, key: AttemptKey) -> _Row | None:
        """The release's own fenced read: `AttemptStore.load` refuses an admitted attempt that never registered its entry."""
        con = self.store.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        row: tuple[object, ...] | None = con.execute(ROW, astuple(key)).fetchone()
        if row is None:
            return None
        return replace(_row(row, key), setup=running(con, key.attempt_id))

    def _refusal(self, row: _Row, abandon: bool, me: EntryIdentity | None) -> NotReleased | None:
        """Read before anything changes: the reservation held, the result collected (settled only), the stop proof."""
        if row.slot_path is None or row.successor:
            return NotReleased("unavailable", "changed", f"The attempt no longer holds its reservation. {NOTHING}")
        if not abandon:
            result = collect(self.store, row.key)
            if result.status == "unavailable":
                return NotReleased("unavailable", "store", f"The result could not be read. {NOTHING}")
            if result.status != "collected":
                return NotReleased("refused", "not_terminal", f"The step has not ended: finish it, repeat it, or abandon it. {NOTHING}")
        return (stop_proof(self.observe, self.gone, me, row.stopping) or setup_stopped(self.setup_seen, row.setup)
                or self._merge_stopped(row))

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

    def _parked(self, row: _Row, path: Path, abandon: bool) -> Released | NotReleased:
        """Under the lock: the slot read and its park, then the transaction."""
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

        def save(view: Repo, slot: Worktree, state: SlotState) -> wip.Refused | None:
            head = state.head or row.slot_head
            if slot.merging() and source.merge is not None:
                target = self.slot_files.read(state.gitdir / "MERGE_HEAD", 256)
                if target != f"{source.merge[1]}\n".encode("ascii"):
                    return wip.Refused(wip.SaveReason.MERGE_CHANGED,
                                       "The active merge's target changed or cannot be read; work stays reserved.")
            saved_head = any(each.source_head == head for each in log.saved(row.key.attempt_id))
            if not state.dirty and not slot.merging() and (source.merge is None or saved_head):
                wip.adopt(view, head, source, log)
                return None
            refused = wip.save(view, slot, source, head, int(self.clock()), log)
            if refused is None and slot.merging() and source.merge is not None:
                slot.abort_merge()  # preservation and its durable record precede the abort
            return refused

        return save

    def _record(self, row: _Row, head: str, abandon: bool) -> bool:
        """One write transaction, fenced on what the proof read: the release row in, the reservation out."""
        key = row.key
        with self._writing() as con:
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
            return NotReleased("unavailable", "tracker", f"Released; the tracker claim is still to be returned ({error.kind}): rerun "
                               "`tl step release --abandon`.")
        claim: Literal["unclaimed", "not_held"] = "unclaimed" if back else "not_held"
        try:
            with self._writing() as con:
                con.execute("UPDATE slot_release SET claim=? WHERE attempt_id=? AND claim='unclaiming'", (claim, row.key.attempt_id))
        except (sqlite3.Error, StoreUnavailable) as error:
            unrecorded = f"Released and the claim {claim}, but that was not recorded ({type(error).__name__}): rerun."
            return NotReleased("unavailable", "store", unrecorded)
        return claim
