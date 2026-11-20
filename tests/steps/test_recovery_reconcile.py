"""Read-only process adoption boundaries retain durable authorization and execution fences."""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_recovery import Processes, recovery
from test_recovery_registration import WORKER, intended
from test_recovery_snapshot import capture
from test_recovery_store import CHANGES, KEY, OWNED, OWNER, database, observed

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import Admission
from taskloop.drain.models import Seen
from taskloop.evidence_files import EvidenceFiles
from taskloop.recovery.models import Claim, ClaimState, Outcome, Reconciliation, ReconciliationState, Result
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


@pytest.mark.parametrize(("entry", "worker", "state"), [
    (Seen.GONE, Seen.ALIVE, ReconciliationState.LIVE),
    (Seen.UNKNOWN, Seen.ALIVE, ReconciliationState.LIVE),
    (Seen.GONE, Seen.GONE, ReconciliationState.GONE),
    (Seen.ALIVE, Seen.GONE, ReconciliationState.UNKNOWN),
    (Seen.UNKNOWN, Seen.GONE, ReconciliationState.UNKNOWN),
    (Seen.GONE, Seen.UNKNOWN, ReconciliationState.UNKNOWN),
])
@pytest.mark.parametrize("advanced", [False, True])
def test_reopen_classifies_exact_registered_worker_and_preserves_owner(
    tmp_path: Path, entry: Seen, worker: Seen, state: ReconciliationState, advanced: bool,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    store = RecoveryStore(lambda: con)
    expected = intended(store)
    registered = store.register(expected, WORKER, lambda: 10)
    assert registered.intent is not None
    if not advanced:
        expected = registered.intent
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    processes = Processes()
    processes.states = {7: entry, WORKER.pid: worker, OWNER.pid: Seen.ALIVE}
    app = recovery(con, processes)
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Reconciliation) and result.state is state and result.explanation
    assert result.snapshot is not None
    assert result.key == KEY and result.snapshot == observed(app.store).snapshot
    assert result.snapshot.intent == registered.intent
    assert result.owner is not None and result.owner.seen is Seen.ALIVE
    assert processes.calls == [7, WORKER.pid, OWNER.pid]
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize("execution", [False, True])
@pytest.mark.parametrize(("worker", "state"), [
    (Seen.GONE, ReconciliationState.GONE), (Seen.ALIVE, ReconciliationState.UNKNOWN),
    (Seen.UNKNOWN, ReconciliationState.UNKNOWN),
])
def test_unregistered_intent_never_adopts_a_worker(
    tmp_path: Path, execution: bool, worker: Seen, state: ReconciliationState,
) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    authorized = app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    expected = authorized.intent
    if execution:
        assert app.store.execute(expected, lambda: 10).outcome is Outcome.INTENDED
    processes = Processes()
    processes.states[8] = worker
    app.processes = processes
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Reconciliation) and result.state is state
    assert result.snapshot is not None and result.snapshot.attempt.worker is not None
    assert result.snapshot.attempt.worker.pid == 8
    assert list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize(("change", "outcome"), CHANGES)
def test_changes_during_observation_refuse_stale_adoption(tmp_path: Path, change: str, outcome: Outcome) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)
    saved: list[str] = []

    def claim(_admission: Admission) -> Claim:
        assert not con.in_transaction
        con.execute(change)
        saved.extend(con.iterdump())
        return OWNED

    app.claim = claim
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is outcome and result.explanation
    assert list(con.iterdump()) == saved
    con.close()


@pytest.mark.parametrize("replace", [False, True])
def test_registration_or_authorization_race_requires_fresh_observations(tmp_path: Path, replace: bool) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)

    def claim(_admission: Admission) -> Claim:
        if replace:
            intended(app.store, "replacement")
        else:
            assert app.store.register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
        return OWNED

    app.claim = claim
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is Outcome.CHANGED
    con.close()


@pytest.mark.parametrize("during", [False, True])
def test_capture_is_classified_without_collection(tmp_path: Path, during: bool) -> None:
    con = database(tmp_path / "factory.db")
    processes = Processes()
    app = recovery(con, processes)
    expected = intended(app.store)
    assert app.store.register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    snapshot = observed(app.store).snapshot
    saved: list[str] = []

    def claim(_admission: Admission) -> Claim:
        capture(con, snapshot)
        saved.extend(con.iterdump())
        return OWNED

    if during:
        app.claim = claim
    else:
        claim(snapshot.attempt.admission)
    result = app.reconcile(expected)
    assert isinstance(result, Reconciliation) and result.state is ReconciliationState.CAPTURED
    assert result.snapshot is None and result.explanation
    assert bool(processes.calls) is during
    assert list(con.iterdump()) == saved
    con.close()


@pytest.mark.parametrize("state", [ClaimState.LOST, ClaimState.UNKNOWN])
def test_claim_refusals_preserve_execution(tmp_path: Path, state: ClaimState) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)
    app.claim = lambda _admission: Claim(state=state, explanation="Claim observation explanation.")
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is (
        Outcome.CLAIM_LOST if state is ClaimState.LOST else Outcome.CLAIM_UNKNOWN)
    assert result.explanation == "Claim observation explanation." and list(con.iterdump()) == before
    con.close()


def test_custody_surrounds_observations_and_comparison_and_can_be_supplied(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)
    held = False
    clock_calls = 0

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        nonlocal held
        assert not held
        held = True
        try:
            yield
        finally:
            held = False

    def clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls % 3 != 1:
            assert held
        return 10

    def claim(_admission: Admission) -> Claim:
        assert held and not con.in_transaction
        return OWNED

    app.custody, app.claim, app.clock = custody, claim, clock
    assert isinstance(app.reconcile(expected), Reconciliation)
    with custody(observed(app.store).snapshot.attempt.admission):
        assert isinstance(app.reconcile(expected, custody=nullcontext()), Reconciliation)
    assert not held
    assert clock_calls == 6
    con.close()


@pytest.mark.parametrize(("error", "outcome"), [
    (SlotBusy, Outcome.CUSTODY_BUSY), (SlotLockUnavailable, Outcome.UNAVAILABLE),
    (StoreUnavailable, Outcome.UNAVAILABLE), (ValueError, Outcome.UNAVAILABLE),
])
def test_unavailable_custody_or_storage_is_explained(
    tmp_path: Path, error: Callable[[str], Exception], outcome: Outcome,
) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        raise error("Unavailable")
        yield

    app.custody = custody
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is outcome and result.explanation
    assert list(con.iterdump()) == before
    con.close()


def test_reconciliation_omits_snapshot_only_for_capture(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    snapshot = observed(RecoveryStore(lambda: con)).snapshot
    with pytest.raises(ValidationError):
        Reconciliation(key=KEY, state=ReconciliationState.UNKNOWN, explanation="Unknown")
    with pytest.raises(ValidationError):
        Reconciliation(key=KEY, state=ReconciliationState.CAPTURED, explanation="Captured", snapshot=snapshot)
    con.close()


@pytest.mark.parametrize("change", [
    "UPDATE attempt SET rev=rev+1", "UPDATE attempt SET worker_start='different'",
    "UPDATE attempt SET session_ref='different'", "UPDATE attempt SET entry_start='different'",
])
def test_registered_execution_requires_exact_worker_revision_session_and_entry(tmp_path: Path, change: str) -> None:
    con = database(tmp_path / "factory.db")
    processes = Processes()
    app = recovery(con, processes)
    expected = intended(app.store)
    assert app.store.register(expected, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    con.execute(change)
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is Outcome.CHANGED and result.explanation
    assert not processes.calls and list(con.iterdump()) == before
    con.close()


def test_replaced_authorization_cannot_reconcile_current_execution(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    processes = Processes()
    app = recovery(con, processes)
    old = intended(app.store)
    current = intended(app.store, "replacement")
    assert app.store.register(current, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    before = list(con.iterdump())
    result = app.reconcile(old)
    assert isinstance(result, Result) and result.outcome is Outcome.CHANGED
    assert not processes.calls and list(con.iterdump()) == before
    con.close()


def test_custody_acquisition_drift_refuses_before_observation(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    processes = Processes()
    app = recovery(con, processes)
    expected = intended(app.store)

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        con.execute("UPDATE attempt SET deadline=99")
        yield

    app.custody = custody
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is Outcome.CHANGED
    assert not processes.calls
    con.close()


def test_expiration_at_final_comparison_preserves_allowance_and_artifacts(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    expected = intended(app.store)
    files = EvidenceFiles(tmp_path / "artifacts")
    schema, native = files.prepare(KEY, {"type": "object"}, expected)
    prompt = files.put_launched_input(KEY, "Saved input", expected)
    before_files = {path: path.read_bytes() for path in (Path(schema), tmp_path / "artifacts" / prompt.path)}
    times = iter((10, 10, 100))
    app.clock = lambda: next(times)
    before = list(con.iterdump())
    result = app.reconcile(expected)
    assert isinstance(result, Result) and result.outcome is Outcome.EXPIRED and result.explanation
    assert list(con.iterdump()) == before
    assert {path: path.read_bytes() for path in before_files} == before_files
    assert not Path(native).exists()
    con.close()
