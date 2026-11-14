"""The sole SQL owner of recovery authorization and execution progress."""

import sqlite3

from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.recovery.execution_models import Callback, Phase
from taskloop.recovery.models import Intent


def intent(con: sqlite3.Connection, key: AttemptKey) -> Intent | None:
    row = con.execute("SELECT data FROM recovery_intent WHERE attempt_id=?", (key.attempt_id,)).fetchone()
    if row is None:
        return None
    found = Intent.model_validate_json(row[0])
    if found.key != key:
        raise StoreUnavailable("Recovery record does not match the attempt key")
    return found


class RecoveryReads(StoreConnection):
    def execution(self, key: AttemptKey) -> Intent | None:
        """The selected execution identity, without recovery admission or liveness checks."""
        with self._connection() as con:
            return intent(con, key)


def save(con: sqlite3.Connection, value: Intent, previous: Intent | None) -> None:
    if previous is None:
        con.execute("INSERT INTO recovery_intent(attempt_id,data) VALUES(?,?)", (value.key.attempt_id, value.model_dump_json()))
    else:
        changed = con.execute("UPDATE recovery_intent SET data=? WHERE attempt_id=? AND data=?",
                              (value.model_dump_json(), value.key.attempt_id, previous.model_dump_json())).rowcount
        if changed != 1:
            raise StoreRefused("recovery_changed")


def callback(value: Intent) -> Callback:
    execution = value.execution
    if execution is None or execution.phase is not Phase.REGISTERED or execution.worker is None:
        raise StoreRefused("recovery_unregistered")
    return Callback(key=value.key, generation=value.generation, token=value.token, owner=value.owner, worker=execution.worker)


def fence(con: sqlite3.Connection, key: AttemptKey, identity: Callback | None) -> None:
    current = intent(con, key)
    if current is None:
        if identity is not None:
            raise StoreRefused("recovery_changed")
    elif identity is None or callback(current) != identity:
        raise StoreRefused("recovery_changed")
