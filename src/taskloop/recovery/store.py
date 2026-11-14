"""The recovery table owner and the atomic authorization boundary."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlite_store import begin_immediate

from taskloop.attempt_reads import StoreConnection, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Identity, Seen
from taskloop.drain.store import blocked, boundary
from taskloop.hold_store import recovery_held
from taskloop.recovery.models import ClaimState, Intent, Observations, Outcome, Result, Snapshot


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

    def _intent(self, con: sqlite3.Connection, key: AttemptKey) -> Intent | None:
        row = con.execute("SELECT data FROM recovery_intent WHERE attempt_id=?", (key.attempt_id,)).fetchone()
        if row is None:
            return None
        intent = Intent.model_validate_json(row[0])
        if intent.key != key:
            raise StoreUnavailable("Recovery record does not match the attempt key")
        return intent

    def _snapshot(self, con: sqlite3.Connection, key: AttemptKey, now: float) -> Snapshot | Result:
        record = self.attempts.recovery(con, key, now)
        if isinstance(record, Result):
            return record
        if recovery_held(con, key.attempt_id):
            return Result(outcome=Outcome.INELIGIBLE, explanation="The attempt is explicitly held.")
        if blocked(con):
            return Result(outcome=Outcome.DRAINING, explanation="Recovery authorization is closed while the factory drains.")
        return Snapshot(attempt=record, drain=boundary(con), intent=self._intent(con, key))

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
        if old is None:
            con.execute("INSERT INTO recovery_intent(attempt_id,data) VALUES(?,?)", (intent.key.attempt_id, intent.model_dump_json()))
        else:
            changed = con.execute("UPDATE recovery_intent SET data=? WHERE attempt_id=? AND data=?",
                                  (intent.model_dump_json(), intent.key.attempt_id, old.model_dump_json())).rowcount
            if not changed:
                return Result(outcome=Outcome.CHANGED, explanation="The observed recovery owner was replaced.")
        return Result(outcome=Outcome.AUTHORIZED, explanation="Stopped eligible work has a durable recovery owner.", intent=intent)
