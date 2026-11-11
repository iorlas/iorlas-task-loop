"""Commit, check clean, then judge: the one operation that settles a stored valid answer of effect `commit` or `keep`.

The entry (once, after the run), `tl plan verify` and a repeating `tl plan start` run the same operation; running it
again finishes a crash at any step. A stored verdict is returned with no Git read; slot state and every unknown store
nothing. The commit through the verdict runs under the slot's custody lock (`hold`); a stored verdict, a refusal, the
leftovers and the staged read take none. Right before each factory Git write the attempt must still hold the
reservation: a verify of an attempt that a repeat took over is `superseded`, never a commit on the next attempt's slot.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from git_porcelain import GitUnavailable

from taskloop.attempt import committing, end_word
from taskloop.attempt_store import AttemptStore, StoreRefused, StoreUnavailable
from taskloop.attempt_types import (
    Admission,
    AttemptKey,
    AttemptRecord,
    Checkouts,
    NotApplicable,
    Rejected,
    SlotFiles,
    StoredExecution,
    Unreadable,
    Unsettled,
    Verdict,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
    WorkerGone,
)
from taskloop.factory_commit import NotSettled, clean_at, leftovers, settle
from taskloop.slot_lock import ReadOnly, SlotBusy, SlotLockUnavailable
from taskloop.slot_state import bounded, staged
from taskloop.steps import kind
from taskloop.verdict import judge

type VerifyHold = Callable[[Admission], AbstractContextManager[None]]
LOCK_WORDS: dict[type[Exception], str] = {
    SlotBusy: "slot_busy",
    SlotLockUnavailable: "lock",
    ReadOnly: "read_only",
}  # the slot lock's refusals, as `unavailable:<word>`


def applicable(stored: StoredExecution | None) -> StoredExecution | VerifyResult:
    """The stored execution when a verdict is still to be made; otherwise what `verify` returns, with no Git read."""
    if stored is None:
        return VerifyRefused("not_captured")
    if stored.answer.kind == "validation_pending":
        return VerifyUnavailable("validation_pending")
    if stored.verification is not None:
        return stored.verification
    if not committing(stored):
        return NotApplicable(end_word(stored))
    if stored.session_state != "complete":  # the verdict's writer requires a complete session state too
        return VerifyRefused("session") if stored.session_state == "conflict" else VerifyUnavailable("session_" + stored.session_state)
    return stored


class Verifier:
    """Git evidence for a stored valid `planned` or `unchanged` answer: the factory's commit of the listed paths, the
    clean tree at it, then one verdict over immutable facts, stored once and then returned with no Git read."""

    def __init__(
        self, store: AttemptStore, checkouts: Checkouts, files: SlotFiles, gone: WorkerGone, clock: Callable[[], float], hold: VerifyHold
    ) -> None:
        """`gone` observes the registered worker before the factory writes Git in its slot (`worker_alive` otherwise).
        `hold` is the slot's custody around the commit through the verdict: the entry already holds it (a no-op here),
        `tl plan verify` and a repeat take it (`slot_lock.hold`), a read-only verifier refuses it (`slot_lock.refused`).
        A held slot is `unavailable:slot_busy`, an unopenable lock file `unavailable:lock`, a write asked of a read-only
        verifier `unavailable:read_only`."""
        self.store, self.checkouts, self.files, self.gone, self.clock, self.hold = store, checkouts, files, gone, clock, hold

    def verify(self, key: AttemptKey) -> VerifyResult:
        try:
            return self._verify(key)
        except StoreUnavailable:
            return VerifyUnavailable("store")
        except StoreRefused as error:
            return VerifyRefused(str(error))
        except NotSettled as error:
            return VerifyUnavailable(error.reason)
        except (SlotBusy, SlotLockUnavailable, ReadOnly) as error:
            return VerifyUnavailable(LOCK_WORDS[type(error)])
        except (GitUnavailable, Unreadable) as error:
            return VerifyUnavailable("git:" + type(error).__name__)

    def _verify(self, key: AttemptKey) -> VerifyResult:
        """A stored verdict or a refusal takes no lock; otherwise everything is read again under the slot's lock, so the
        commit through the verdict never acts on a record read before it."""
        found = self._ready(key)
        if not isinstance(found, tuple):
            return found
        with self.hold(found[0].admission):
            again = self._ready(key)
            return again if not isinstance(again, tuple) else self._settle(*again)

    def _ready(self, key: AttemptKey) -> tuple[AttemptRecord, str, StoredExecution] | VerifyResult:
        stored = applicable(self.store.collect(key))
        if not isinstance(stored, StoredExecution):
            return stored
        record = self.store.load(key)
        if record is None or record.base_commit is None:
            return VerifyRefused("absent" if record is None else "no_base")
        return record, record.base_commit, stored

    def leftovers(self, key: AttemptKey) -> Unsettled | None:
        """Read-only: the leftovers a verify would report for a step still to settle, read now; None when there is
        nothing to report or it cannot be read (the person runs `tl plan verify` for the reason)."""
        try:
            stored = applicable(self.store.collect(key))
            record = self.store.load(key)
            if not isinstance(stored, StoredExecution) or record is None or record.base_commit is None:
                return None
            admission = record.admission
            return leftovers(self.checkouts, self.files, admission, record.base_commit, stored.answer, record.end_commit)
        except (StoreUnavailable, StoreRefused, NotSettled, GitUnavailable, Unreadable):
            return None

    def staged(self, key: AttemptKey) -> tuple[str, ...] | None:
        """Read-only: the paths staged in the attempt's slot now (`bounded`); None when unknown. A repeat refuses a staged
        index before it takes the step over: the next attempt's dispatch would refuse it anyway, after spending a number."""
        try:
            record = self.store.load(key)
            if record is None:
                return None
            path = Path(record.admission.slot_path)
            return bounded(staged(self.checkouts(path), path))
        except (StoreUnavailable, StoreRefused, GitUnavailable):
            return None

    def _quiet(self, record: AttemptRecord) -> Unsettled | None:
        """Asked right before each factory Git write: this attempt still holds the reservation (a fresh fenced load, else
        `superseded`) and its registered worker is gone (a captured attempt always has one; none counts as alive)."""
        try:
            held = self.store.load(record.admission.key)
        except StoreRefused:
            held = None
        if held is None or held.admission != record.admission:
            return Unsettled("superseded")
        worker = record.worker
        return None if worker is not None and self.gone(worker) else Unsettled("worker_alive")

    def _settle(self, record: AttemptRecord, base: str, stored: StoredExecution) -> VerifyResult:
        """Outside any transaction: X (stored, adopted or made), then the clean tree at X, then the verdict over the
        step's chain."""
        admission, answer, commit = record.admission, stored.answer, record.end_commit
        if commit is None:
            settled = settle(self.checkouts, self.files, admission, base, answer, lambda: self._quiet(record))
            if isinstance(settled, Unsettled):
                return settled
            if isinstance(settled, Rejected):  # nothing_written: no commit to bind
                return self._kept(record, base, None, settled)
            commit = settled.sha if answer.effect == "keep" else self.store.end_commit(admission, settled.sha)
            if commit != settled.sha:
                return VerifyUnavailable("inconsistent")
        root = clean_at(self.checkouts, self.files, admission, commit)
        if isinstance(root, Unsettled):
            return root
        if record.end_commit is None and answer.effect == "keep" and self.store.end_commit(admission, commit) != commit:
            return VerifyUnavailable("inconsistent")
        step = kind(admission.step)
        found = judge(self.checkouts(root), root, commit, step, step.rules(admission.task.task_id), self.store.chain(admission.key))
        return self._kept(record, base, commit, found)

    def _kept(self, record: AttemptRecord, base: str, commit: str | None, found: Verdict) -> Verdict | VerifyUnavailable:
        kept = self.store.verdict(record.admission, base, commit, found, self.clock())
        return found if kept == found else VerifyUnavailable("inconsistent")  # same inputs, same rules: a defect

