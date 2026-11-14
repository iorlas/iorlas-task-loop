"""The recovery table owner and the atomic authorization boundary."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from any_agent.procs import Worker
from sqlite_store import begin_immediate

from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Identity, Seen
from taskloop.drain.store import blocked, boundary
from taskloop.hold_store import recovery_held
from taskloop.recovery.execution_models import Execution, Phase
from taskloop.recovery.models import ClaimState, Intent, Observations, Outcome, Result, Snapshot
from taskloop.recovery.state_store import intent as read_intent
from taskloop.recovery.state_store import save


def worker_value(identity: Identity) -> Worker:
    return Worker(pid=identity.pid, pgid=identity.pgid, start=identity.start, boot=identity.boot)


def permitted(observed: Observations, owner: Identity, token: str) -> Result | None:
    """All world facts are tied to the exact local snapshot passed to the committing fence."""
    for seen in (observed.entry, observed.worker):
        if seen.seen is not Seen.GONE:
            return Result(outcome=Outcome.UNRESOLVED, explanation=seen.explanation)
    previous = observed.snapshot.intent
    if (previous is not None and (previous.owner != owner or previous.token != token)
            and (observed.owner is None or observed.owner.seen is not Seen.GONE)):
        explanation = "The previous recovery owner has no stop proof." if observed.owner is None else observed.owner.explanation
        return Result(outcome=Outcome.OCCUPIED, explanation=explanation, intent=previous)
    if observed.claim.state is not ClaimState.OWNED:
        outcome = Outcome.CLAIM_LOST if observed.claim.state is ClaimState.LOST else Outcome.CLAIM_UNKNOWN
        return Result(outcome=outcome, explanation=observed.claim.explanation)
    return None


class RecoveryStore(StoreConnection):
    def __init__(
        self, connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
    ) -> None:
        super().__init__(connect, begin)
        self.attempts = AttemptStore(connect, begin)

    def execute(self, expected: Intent, clock: Callable[[], float]) -> Result:
        """Record launch intent before a caller performs an external launch."""
        with self._connection(write=True) as con:
            snapshot = self._snapshot(con, expected.key, clock())
            if isinstance(snapshot, Result):
                return snapshot
            if snapshot.intent != expected or snapshot.attempt.revision != expected.attempt_revision:
                return Result(outcome=Outcome.CHANGED, explanation="The execution authorization changed.")
            value = expected.model_copy(update={"execution": expected.execution or Execution(drain=snapshot.drain)})
            save(con, value, expected)
            return Result(outcome=Outcome.INTENDED, explanation="The authorized execution intent is durable.", intent=value)

    def register(self, expected: Intent, worker: Identity, clock: Callable[[], float]) -> Result:
        """Bind the worker and execution record in one short transaction, before delivering its permit."""
        with self._connection(write=True) as con:
            snapshot = self._snapshot(con, expected.key, clock())
            if isinstance(snapshot, Result):
                return snapshot
            current = snapshot.intent
            if (current is None or current.execution is None or expected.execution is None
                    or current.execution.drain != snapshot.drain
                    or current.model_dump(exclude={"execution"}) != expected.model_dump(exclude={"execution"})):
                return Result(outcome=Outcome.CHANGED, explanation="The execution intent, owner, generation or drain boundary changed.")
            execution = current.execution
            if execution.phase is Phase.REGISTERED:
                if execution.worker == worker and snapshot.attempt.worker == worker_value(worker):
                    return Result(outcome=Outcome.REGISTERED, explanation="This exact worker is already registered.", intent=current)
                return Result(outcome=Outcome.OCCUPIED, explanation="A different worker already owns this execution.")
            try:
                revision = self.attempts.replace_worker(con, snapshot.attempt, current, worker)
            except StoreRefused:
                return Result(outcome=Outcome.CHANGED, explanation="The attempt changed before worker registration.")
            execution = Execution(drain=execution.drain, phase=Phase.REGISTERED, worker=worker, revision=revision)
            value = current.model_copy(update={"execution": execution})
            save(con, value, current)
            return Result(outcome=Outcome.REGISTERED, explanation="The authorized worker registration is durable.", intent=value)

    def _snapshot(self, con: sqlite3.Connection, key: AttemptKey, now: float) -> Snapshot | Result:
        record = self.attempts.recovery(con, key, now)
        if isinstance(record, Result):
            return record
        if recovery_held(con, key.attempt_id):
            return Result(outcome=Outcome.INELIGIBLE, explanation="The attempt is explicitly held.")
        if blocked(con):
            return Result(outcome=Outcome.DRAINING, explanation="Recovery authorization is closed while the factory drains.")
        return Snapshot(attempt=record, drain=boundary(con), intent=read_intent(con, key))

    def snapshot(self, key: AttemptKey, now: float) -> Snapshot | Result:
        with self._connection(write=True) as con:
            return self._snapshot(con, key, now)

    def authorize(self, observed: Observations, owner: Identity, token: str, clock: Callable[[], float]) -> Result:
        refusal = permitted(observed, owner, token)
        if refusal is not None:
            return refusal
        expected = observed.snapshot
        key = expected.attempt.admission.key
        with self._connection(write=True) as con:
            current = self._snapshot(con, key, clock())
            if isinstance(current, Result):
                return current
            if current != expected:
                return Result(outcome=Outcome.CHANGED, explanation="Recovery facts or ownership changed after observation.",
                              intent=current.intent)
            return self._authorize(con, current, owner, token)

    def _authorize(self, con: sqlite3.Connection, snapshot: Snapshot, owner: Identity, token: str) -> Result:
        old, record = snapshot.intent, snapshot.attempt
        if old is not None and old.owner == owner and old.token == token:
            if old.attempt_revision != record.revision or old.session != record.session_ref:
                return Result(outcome=Outcome.CHANGED, explanation="The saved authorization no longer matches the attempt.", intent=old)
            return Result(outcome=Outcome.AUTHORIZED, explanation="This owner retains the revalidated recovery authorization.", intent=old)
        worker = record.worker
        if worker is None or record.session_ref is None:
            raise StoreUnavailable("Recovery snapshot has incomplete registration")
        intent = Intent(key=record.admission.key, generation=1 if old is None else old.generation + 1,
                        token=token, owner=owner, attempt_revision=record.revision, session=record.session_ref,
                        entry=record.admission.entry,
                        worker=Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot))
        save(con, intent, old)
        return Result(outcome=Outcome.AUTHORIZED, explanation="Stopped eligible work has a durable recovery owner.", intent=intent)
