"""Reopened execution intents and ambiguous effects never grant duplicate execution."""

import sqlite3
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

import pytest
from sqlite_store import begin_immediate
from test_attempt import AttemptSurroundings
from test_attempt import surroundings as attempt_surroundings
from test_native_continuation import WORKER, NativeRun, prepared
from test_recovery import Processes, recovery
from test_recovery_registration import intended
from test_recovery_store import CHANGES, KEY, OWNED, OWNER, database

from taskloop import attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission
from taskloop.drain.models import Seen
from taskloop.recovery.callbacks import PendingExecution
from taskloop.recovery.continuation_models import State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.models import Claim, ClaimState, Outcome
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.store import RecoveryStore

surroundings = attempt_surroundings


@pytest.mark.parametrize("boundary", ["before_intent", "after_authorize", "after_intent", "after_register", "lost_ack"])
@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.GONE, Seen.UNKNOWN])
def test_crash_reopen_observes_before_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, boundary: str, seen: Seen,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    app = recovery(con)
    if boundary == "after_authorize":
        assert app.authorize(KEY, OWNER).intent is not None
    elif boundary in ("after_intent", "after_register", "lost_ack"):
        intent = intended(app.store)
        if boundary in ("after_register", "lost_ack"):
            @contextmanager
            def lost_ack(connection: sqlite3.Connection) -> Generator[None]:
                with begin_immediate(connection):
                    yield
                raise sqlite3.OperationalError("lost acknowledgement")

            native = NativeContinuation(attempts, RecoveryStore(lambda: con, lost_ack) if boundary == "lost_ack" else app.store)
            record = attempts.store.load(KEY)
            assert record is not None
            native(record.admission, intent)  # discard returned facts, as if the entry crashed
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    processes = Processes()
    registered = boundary in ("after_register", "lost_ack")
    processes.states[WORKER.pid if registered else 8] = seen
    processes.states[OWNER.pid] = Seen.GONE
    reopened = surroundings.attempts(AttemptStore(lambda: con), execution)
    app = Continuation(recovery(con, processes), reopened, NativeContinuation(reopened, RecoveryStore(lambda: con)))
    before = execution.permits
    result = app(KEY, OWNER)
    assert result.explanation
    if seen is Seen.GONE:
        assert result.state is State.COMPLETED and execution.permits == before + 1
        identity = reopened.store.callback(KEY)
        assert identity is not None and identity.generation == (2 if registered else 1)
    elif seen is Seen.ALIVE and registered:
        assert result.state is State.LIVE and result.intent is not None
        assert result.intent.execution is not None and result.intent.execution.worker is not None
        assert result.intent.execution.worker.pid == WORKER.pid and execution.permits == before
    else:
        assert result.state is State.REFUSED and execution.permits == before
    assert execution.permits <= (2 if boundary == "after_register" and seen is Seen.GONE else 1)
    con.close()


@pytest.mark.parametrize(("change", "outcome"), CHANGES)
def test_local_fences_refuse_before_native_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, change: str, outcome: Outcome,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)

    def changed(_admission: Admission) -> Claim:
        con.execute(change)
        return OWNED

    recovery_app.claim = changed
    app = Continuation(recovery_app, attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))
    result = app(KEY, OWNER)
    assert result.state is State.REFUSED and result.refusal is not None and result.refusal.outcome is outcome
    assert execution.calls == [] and execution.permits == 0
    con.close()


def test_stopped_registered_worker_requires_owner_stop_proof(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    intent = intended(recovery_app.store)
    record = attempts.store.load(KEY)
    assert record is not None
    native = NativeContinuation(attempts, recovery_app.store)
    assert isinstance(native(record.admission, intent), PendingExecution)
    processes = Processes()
    processes.states[OWNER.pid] = Seen.UNKNOWN
    recovery_app.processes = processes
    result = Continuation(recovery_app, attempts, native)(KEY, OWNER)
    assert result.refusal is not None and result.refusal.outcome is Outcome.OCCUPIED
    assert execution.permits == 1 and len(execution.calls) == 1
    con.close()


def test_old_pending_capture_cannot_overwrite_successor(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    intent = intended(recovery_app.store)
    record = attempts.store.load(KEY)
    assert record is not None
    native = NativeContinuation(attempts, recovery_app.store)
    old = native(record.admission, intent)
    assert isinstance(old, PendingExecution)
    app = Continuation(recovery_app, attempts, native)
    assert app(KEY, OWNER).state is State.COMPLETED
    saved = attempts.store.collect(KEY)
    stale = app.capture(old)
    assert stale.refusal is not None and stale.refusal.outcome is Outcome.CONFLICT
    assert attempts.store.collect(KEY) == saved and execution.permits == 2
    con.close()


def test_crash_before_decoding_reopens_captured_work_without_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    app = Continuation(recovery(con), attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))

    def crashed(*_args: object) -> None:
        raise RuntimeError("entry crashed before decoding")

    with monkeypatch.context() as patch:
        patch.setattr(attempt, "decode_answer", crashed)
        with pytest.raises(RuntimeError, match="before decoding"):
            app(KEY, OWNER)
    stored = attempts.store.collect(KEY)
    assert stored is not None and stored.answer.kind == "validation_pending"
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    reopened = surroundings.attempts(AttemptStore(lambda: con), execution)
    app = Continuation(recovery(con), reopened, NativeContinuation(reopened, RecoveryStore(lambda: con)))
    assert app(KEY, OWNER).state is State.COMPLETED and len(execution.calls) == 1 and execution.permits == 1
    con.close()


def test_capture_retry_and_captured_restart_never_execute(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    down = False
    attempts.store = AttemptStore(lambda: None if down else con)

    def storage_lost() -> None:
        nonlocal down
        down = True

    execution.after_start = storage_lost
    app = Continuation(recovery(con), attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))
    result = app(KEY, OWNER)
    assert result.state is State.PENDING_CAPTURE and result.pending is not None
    down = False
    assert app.capture(result.pending).state is State.COMPLETED
    con.close()
    con = sqlite3.connect(path, isolation_level=None)
    reopened = surroundings.attempts(AttemptStore(lambda: con), execution)
    app = Continuation(recovery(con), reopened, NativeContinuation(reopened, RecoveryStore(lambda: con)))
    assert app(KEY, OWNER).state is State.COMPLETED
    assert len(execution.calls) == 1 and execution.permits == 1
    con.close()


@pytest.mark.parametrize("claim", [Claim(state=ClaimState.LOST, explanation="Claim lost."), OWNED])
def test_claim_and_already_held_custody(tmp_path: Path, surroundings: AttemptSurroundings, claim: Claim) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    recovery_app.claim = lambda _admission: claim

    def forbidden(_admission: Admission) -> AbstractContextManager[None]:
        raise AssertionError("Custody was acquired twice")

    recovery_app.custody = forbidden
    app = Continuation(recovery_app, attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))
    result = app(KEY, OWNER, custody=nullcontext())
    assert result.state is (State.COMPLETED if claim.state is ClaimState.OWNED else State.REFUSED)
    assert execution.permits == (1 if claim.state is ClaimState.OWNED else 0)
    if result.refusal is not None:
        assert result.refusal.outcome is Outcome.CLAIM_LOST
    con.close()
