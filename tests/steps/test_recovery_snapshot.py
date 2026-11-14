"""Snapshot comparisons fence all observations without changing durable state."""

import sqlite3
from pathlib import Path

import pytest
from test_recovery_registration import WORKER, intended
from test_recovery_store import CHANGES, OWNER, database, observed, seed

from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Evidence, ExecutionFacts, FileRef
from taskloop.recovery.models import Outcome, Result, Snapshot
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore


def capture(con: sqlite3.Connection, snapshot: Snapshot) -> None:
    assert snapshot.intent is not None
    files = FileRef("evidence", "digest")
    execution = ExecutionFacts(0, False, None, None, True, True, True, None, None, None, None, None, "saved")
    assert AttemptStore(lambda: con).capture(
        snapshot.attempt.admission, None, execution, Evidence(files, files, files, files), "complete", callback(snapshot.intent),
    ) == "accepted"


def test_exact_snapshot_comparison_is_read_only_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    store = RecoveryStore(lambda: con)
    expected = intended(store)
    snapshot = observed(store).snapshot
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    store = RecoveryStore(lambda: con)
    before = list(con.iterdump())
    assert store.compare(snapshot, lambda: 10) == snapshot
    assert snapshot.intent == expected
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize(("change", "outcome"), [*CHANGES,
    ("UPDATE attempt SET session_ref='other'", Outcome.CHANGED),
    ("UPDATE attempt SET entry_start='other'", Outcome.CHANGED),
    ("UPDATE attempt SET worker_pgid=99", Outcome.CHANGED),
])
def test_comparison_preserves_drift_and_eligibility_results(tmp_path: Path, change: str, outcome: Outcome) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    intended(store)
    snapshot = observed(store).snapshot
    con.execute(change)
    before = list(con.iterdump())
    result = store.compare(snapshot, lambda: 10)
    assert isinstance(result, Result) and result.outcome is outcome and result.explanation
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize("registration", [False, True])
def test_ownership_or_registration_advancement_invalidates_snapshot(tmp_path: Path, registration: bool) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    expected = intended(store)
    snapshot = observed(store).snapshot
    if registration:
        assert store.register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    else:
        assert store.authorize(observed(store), OWNER, "replacement", lambda: 10).outcome is Outcome.AUTHORIZED
    before = list(con.iterdump())
    result = store.compare(snapshot, lambda: 10)
    assert isinstance(result, Result) and result.outcome is Outcome.CHANGED and result.explanation
    assert list(con.iterdump()) == before
    con.close()


def test_capture_takes_precedence_over_other_snapshot_drift(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    expected = intended(store)
    assert store.register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    snapshot = observed(store).snapshot
    capture(con, snapshot)
    con.execute("INSERT INTO drain_state VALUES(1,1,'draining')")
    before = list(con.iterdump())
    result = store.compare(snapshot, lambda: 100)
    assert isinstance(result, Result) and result.outcome is Outcome.CAPTURED and result.explanation
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize("successor", [False, True])
def test_session_claim_or_successor_prevents_comparison(tmp_path: Path, successor: bool) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    snapshot = observed(store).snapshot
    seed(con, attempt="other", task="tl-2", session="other" if successor else "saved")
    if successor:
        con.execute("UPDATE attempt SET task_id='tl-1',seq=2 WHERE attempt_id='other'")
    before = list(con.iterdump())
    result = store.compare(snapshot, lambda: 10)
    assert isinstance(result, Result) and result.outcome is Outcome.INELIGIBLE and result.explanation
    assert list(con.iterdump()) == before
    con.close()


def test_comparison_clock_runs_inside_transaction(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    store = RecoveryStore(lambda: con)
    snapshot = observed(store).snapshot

    def clock() -> float:
        assert con.in_transaction
        return 100

    result = store.compare(snapshot, clock)
    assert isinstance(result, Result) and result.outcome is Outcome.EXPIRED
    assert not con.in_transaction
    con.close()
