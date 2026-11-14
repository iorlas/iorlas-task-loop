"""Registered-start permits require one durable full worker identity."""

import json
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest
from any_agent.procs import Worker
from sqlite_store import begin_immediate
from test_recovery_store import CHANGES, OWNER, database, facts, observed

from taskloop.attempt_reads import StoreUnavailable
from taskloop.drain.models import Identity
from taskloop.recovery.models import Intent, Outcome
from taskloop.recovery.registration import registration_hook
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore
from taskloop.session import RegistrationRefused

WORKER = Identity(pid=80, pgid=81, start="replacement", boot="boot")


def intended(store: RecoveryStore, token: str = "token") -> Intent:
    authorized = store.authorize(observed(store), OWNER, token, lambda: 10)
    assert authorized.intent is not None, authorized
    result = store.execute(authorized.intent, lambda: 10)
    assert result.outcome is Outcome.INTENDED and result.intent is not None
    return result.intent


def test_independent_registration_winners_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    expected = intended(RecoveryStore(lambda: con))
    con.close()
    barrier = Barrier(2)

    def contend(pgid: int) -> Outcome:
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            store = RecoveryStore(lambda: connection)
            barrier.wait(timeout=5)
            return store.register(expected, WORKER.model_copy(update={"pgid": pgid}), lambda: 10).outcome
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contend, (81, 82)))
    assert sorted(results) == sorted((Outcome.REGISTERED, Outcome.OCCUPIED))
    con = sqlite3.connect(path, isolation_level=None)
    store = RecoveryStore(lambda: con)
    current = observed(store).snapshot.intent
    assert current is not None and current.execution is not None and current.execution.worker is not None
    worker = current.execution.worker
    assert con.execute("SELECT worker_pid,worker_pgid,worker_start,worker_boot,rev FROM attempt").fetchone() == (
        worker.pid, worker.pgid, worker.start, worker.boot, 5)
    assert store.register(expected, worker, lambda: 10).intent == current
    assert callback(current).worker == worker
    con.close()


@pytest.mark.parametrize(("change", "expected_outcome"), CHANGES)
def test_registration_rechecks_local_fences(tmp_path: Path, change: str, expected_outcome: Outcome) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    expected = intended(store)
    con.execute(change)
    before = facts(con)
    result = store.register(expected, WORKER, lambda: 10)
    assert result.outcome is expected_outcome and result.explanation
    assert facts(con) == before
    assert con.execute("SELECT data FROM recovery_intent").fetchone() == (expected.model_dump_json(),)
    con.close()


def test_replaced_owner_and_old_generation_never_get_permit(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    old = intended(store)
    current = intended(store, "replacement")
    before = facts(con)
    hook = registration_hook(store, old, lambda: 10)
    executed = []
    with pytest.raises(RegistrationRefused):
        hook(Worker(pid=80, pgid=81, start="replacement", boot="boot"))
        executed.append(True)
    assert executed == [] and facts(con) == before
    assert store.register(current, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    con.close()


def test_registration_rolls_back_both_writes_and_storage_loss_blocks_permit(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    expected = intended(RecoveryStore(lambda: con))
    before = facts(con)

    @contextmanager
    def fail_commit(connection: sqlite3.Connection) -> Generator[None]:
        with begin_immediate(connection):
            yield
            raise sqlite3.OperationalError("lost commit")

    for store in (RecoveryStore(lambda: con, fail_commit), RecoveryStore(lambda: None)):
        with pytest.raises(StoreUnavailable):
            registration_hook(store, expected, lambda: 10)(Worker(pid=80, pgid=81, start="replacement", boot="boot"))
    assert facts(con) == before
    assert con.execute("SELECT data FROM recovery_intent").fetchone() == (expected.model_dump_json(),)
    @contextmanager
    def lost_ack(connection: sqlite3.Connection) -> Generator[None]:
        with begin_immediate(connection):
            yield
        raise sqlite3.OperationalError("acknowledgement lost after commit")

    executed = []
    with pytest.raises(StoreUnavailable):
        registration_hook(RecoveryStore(lambda: con, lost_ack), expected, lambda: 10)(
            Worker(pid=80, pgid=81, start="replacement", boot="boot"))
        executed.append(True)
    assert executed == []
    con.close()
    con = sqlite3.connect(tmp_path / "factory.db", isolation_level=None)
    assert RecoveryStore(lambda: con).register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    con.close()


@pytest.mark.parametrize("execution", [
    {}, {"phase": "registered"},
    {"drain": {"generation": 0, "state": "open"}, "phase": "registered", "worker": None, "revision": 5},
    {"drain": {"generation": 0, "state": "open"}, "phase": "registered",
     "worker": {"pid": 80, "pgid": 81, "start": "new", "boot": "boot"}, "revision": 999},
])
def test_malformed_execution_records_are_preserved_as_unavailable(tmp_path: Path, execution: dict[str, object]) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    original = intended(store)
    data = json.loads(original.model_dump_json())
    data["execution"] = execution
    encoded = json.dumps(data)
    con.execute("UPDATE recovery_intent SET data=?", (encoded,))
    before = facts(con)
    with pytest.raises(StoreUnavailable):
        store.snapshot(original.key, 10)
    assert facts(con) == before
    assert con.execute("SELECT data FROM recovery_intent").fetchone() == (encoded,)
    con.close()
