"""Reconcile an existing attempt and authorize recovery; execution belongs to a later operation."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import Admission, AttemptKey, EntryIdentity
from taskloop.drain.models import Identity, Seen
from taskloop.ids import Ids
from taskloop.recovery.execution_models import Phase
from taskloop.recovery.models import (
    Claim,
    ClaimState,
    Intent,
    Observations,
    Outcome,
    ProcessObservation,
    Reconciliation,
    ReconciliationState,
    Result,
    Snapshot,
)
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


def matches(expected: Intent, snapshot: Snapshot) -> bool:
    """Execution may advance, but authorization and its registered identity must remain exact."""
    current, record = snapshot.intent, snapshot.attempt
    if current is None or current.model_dump(exclude={"execution"}) != expected.model_dump(exclude={"execution"}):
        return False
    execution, previous = current.execution, expected.execution
    if previous is not None and (execution is None or execution.drain != previous.drain
                                 or (previous.phase is Phase.REGISTERED and execution != previous)):
        return False
    if execution is not None and execution.drain != snapshot.drain:
        return False
    worker, revision = current.worker, current.attempt_revision
    if execution is not None and execution.phase is Phase.REGISTERED:
        worker, revision = execution.worker, execution.revision
    saved = record.worker
    return (saved is not None and worker is not None and record.revision == revision
            and (saved.pid, saved.pgid, saved.start, saved.boot) == (worker.pid, worker.pgid, worker.start, worker.boot)
            and record.admission.entry == current.entry and record.session_ref == current.session)


def classify(observed: Observations) -> Reconciliation:
    snapshot = observed.snapshot
    execution = None if snapshot.intent is None else snapshot.intent.execution
    state = ReconciliationState.UNKNOWN
    explanation = "Entry or worker absence cannot be confirmed. " + observed.entry.explanation + " " + observed.worker.explanation
    if execution is not None and execution.phase is Phase.REGISTERED and observed.worker.seen is Seen.ALIVE:
        state, explanation = ReconciliationState.LIVE, observed.worker.explanation
    elif observed.entry.seen is Seen.GONE and observed.worker.seen is Seen.GONE:
        state, explanation = ReconciliationState.GONE, "The entry and worker, including its process group, are confirmed absent."
    return Reconciliation(key=snapshot.attempt.admission.key, state=state, explanation=explanation,
                          snapshot=snapshot, owner=observed.owner)


def captured(key: AttemptKey, result: Result) -> Reconciliation | Result:
    if result.outcome is Outcome.CAPTURED:
        return Reconciliation(key=key, state=ReconciliationState.CAPTURED, explanation=result.explanation)
    return result


class Processes(Protocol):
    def entry(self, identity: EntryIdentity) -> ProcessObservation: ...

    def process(self, identity: Identity) -> ProcessObservation: ...


class Recovery:
    def __init__(
        self, store: RecoveryStore, processes: Processes, claim: Callable[[Admission], Claim],
        custody: Callable[[Admission], AbstractContextManager[None]], clock: Callable[[], float], ids: Ids,
    ) -> None:
        self.store, self.processes, self.claim = store, processes, claim
        self.custody, self.clock, self.ids = custody, clock, ids

    def authorize(
        self, key: AttemptKey, owner: Identity, *, token: str | None = None,
        custody: AbstractContextManager[None] | None = None, deadline: float | None = None,
    ) -> Result:
        """An already-held custody scope bypasses acquisition of the nonreentrant slot lock."""
        try:
            snapshot = self.store.snapshot(key, self.clock(), allow_expired=deadline is not None)
            if isinstance(snapshot, Result):
                return snapshot
            previous = snapshot.intent
            selected = token or (previous.token if previous is not None and previous.owner == owner else self.ids.hex())
            with self.custody(snapshot.attempt.admission) if custody is None else custody:
                observed = self._observe(snapshot)
                return self.store.authorize(observed, owner, selected, self.clock, deadline=deadline)
        except SlotBusy:
            return Result(outcome=Outcome.CUSTODY_BUSY, explanation="The slot's custody is held by another operation.")
        except (StoreUnavailable, ValueError, TypeError, SlotLockUnavailable) as error:
            return Result(outcome=Outcome.UNAVAILABLE,
                          explanation=f"Recovery observations or storage are unavailable ({type(error).__name__}).")

    def reconcile(
        self, expected: Intent, *, custody: AbstractContextManager[None] | None = None,
    ) -> Reconciliation | Result:
        """Observe saved execution under custody; never grant a permit or transfer ownership."""
        try:
            snapshot = self.store.snapshot(expected.key, self.clock())
            if isinstance(snapshot, Result):
                return captured(expected.key, snapshot)
            with self.custody(snapshot.attempt.admission) if custody is None else custody:
                return self._reconcile(expected, snapshot)
        except SlotBusy:
            return Result(outcome=Outcome.CUSTODY_BUSY, explanation="The slot's custody is held by another operation.")
        except (StoreUnavailable, ValueError, TypeError, SlotLockUnavailable) as error:
            return Result(outcome=Outcome.UNAVAILABLE,
                          explanation=f"Recovery observations or storage are unavailable ({type(error).__name__}).")

    def _reconcile(self, expected: Intent, initial: Snapshot) -> Reconciliation | Result:
        snapshot = self.store.compare(initial, self.clock)
        if isinstance(snapshot, Result):
            return captured(expected.key, snapshot)
        if not matches(expected, snapshot):
            return Result(outcome=Outcome.CHANGED, explanation="The saved authorization or execution registration changed.")
        observed = self._observe(snapshot)
        compared = self.store.compare(snapshot, self.clock)
        if isinstance(compared, Result):
            return captured(expected.key, compared)
        if observed.claim.state is not ClaimState.OWNED:
            outcome = Outcome.CLAIM_LOST if observed.claim.state is ClaimState.LOST else Outcome.CLAIM_UNKNOWN
            return Result(outcome=outcome, explanation=observed.claim.explanation)
        return classify(observed)

    def _observe(self, snapshot: Snapshot) -> Observations:
        record = snapshot.attempt
        worker = record.worker
        if worker is None:
            raise StoreUnavailable("Worker registration is incomplete")
        return Observations(
            snapshot=snapshot, entry=self.processes.entry(record.admission.entry),
            worker=self.processes.process(Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot)),
            owner=None if snapshot.intent is None else self.processes.process(snapshot.intent.owner),
            claim=self.claim(record.admission),
        )
