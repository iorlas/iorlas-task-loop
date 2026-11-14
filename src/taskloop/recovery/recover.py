"""Reconcile an existing attempt and authorize recovery; execution belongs to a later operation."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import Admission, AttemptKey, EntryIdentity
from taskloop.drain.models import Identity
from taskloop.ids import Ids
from taskloop.recovery.models import Claim, Observations, Outcome, ProcessObservation, Result, Snapshot
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


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
        custody: AbstractContextManager[None] | None = None,
    ) -> Result:
        """An already-held custody scope bypasses acquisition of the nonreentrant slot lock."""
        try:
            snapshot = self.store.snapshot(key, self.clock())
            if isinstance(snapshot, Result):
                return snapshot
            previous = snapshot.intent
            selected = token or (previous.token if previous is not None and previous.owner == owner else self.ids.hex())
            with self.custody(snapshot.attempt.admission) if custody is None else custody:
                observed = self._observe(snapshot)
                return self.store.authorize(observed, owner, selected, self.clock)
        except SlotBusy:
            return Result(outcome=Outcome.CUSTODY_BUSY, explanation="The slot's custody is held by another operation.")
        except (StoreUnavailable, ValueError, TypeError, SlotLockUnavailable) as error:
            return Result(outcome=Outcome.UNAVAILABLE,
                          explanation=f"Recovery observations or storage are unavailable ({type(error).__name__}).")

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
