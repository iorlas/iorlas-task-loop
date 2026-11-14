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
from test_recovery_callbacks import raw, registered
from test_recovery_registration import intended
from test_recovery_store import CHANGES, KEY, OWNED, OWNER, database

from taskloop import attempt
from taskloop.attempt import Attempts
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission, AttemptKey
from taskloop.attempt_types import Seen as EntrySeen
from taskloop.drain.models import Identity, Seen
from taskloop.hold_store import HoldStore
from taskloop.recovery.callbacks import Callbacks, PendingExecution
from taskloop.recovery.complete_attempt import CapturedCompletion
from taskloop.recovery.continuation_models import State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.models import Claim, ClaimState, Outcome, Result
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.store import RecoveryStore
from taskloop.slot_lock import hold

surroundings = attempt_surroundings


@pytest.fixture
def captured_work(tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch) -> Generator[Attempts]:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    app = prepared(con, surroundings, execution)
    record = app.store.load(KEY)
    assert record is not None
    recovery_store = RecoveryStore(lambda: con)
    callbacks = Callbacks(app, record.admission, registered(recovery_store, intended(recovery_store), WORKER))
    def crashed(*_args: object) -> None:
        raise RuntimeError("entry crashed before decoding")

    with monkeypatch.context() as patch:
        patch.setattr(attempt, "decode_answer", crashed)
        with pytest.raises(RuntimeError, match="before decoding"):
            callbacks.capture(callbacks.returned(raw(WORKER)))
    assert app.store.collect(KEY) is not None
    yield app
    assert execution.calls == [] and execution.permits == 0
    con.close()


@pytest.mark.parametrize("session", ["complete", "pending", "fault"])
def test_captured_completion_finishes_answer_and_session(captured_work: Attempts, session: str) -> None:
    store = captured_work.store
    con = store.connect()
    assert con is not None
    con.execute("UPDATE execution SET session_state=?", (session,))
    con.execute("UPDATE attempt SET deadline=0")
    if session != "complete":
        con.execute("UPDATE attempt SET session_ref=NULL")
    before = con.execute("SELECT * FROM reservation").fetchall()
    app = CapturedCompletion(captured_work, HoldStore(store.connect), hold, lambda _entry: "gone")
    result = app("tasks", "tl-1", KEY.attempt_id)
    assert result.status == "pending" and result.reason == "verification"
    assert result.execution is not None and result.execution.answer.kind == "valid" and result.execution.session_state == "complete"
    assert app("tasks", "tl-1", KEY.attempt_id) == result
    assert con.execute("SELECT * FROM reservation").fetchall() == before
    assert con.execute("SELECT session_ref FROM attempt").fetchone() == ("saved",)


@pytest.mark.parametrize("seen", ["matching", "unknown"])
def test_captured_completion_preserves_live_or_unknown_entry(captured_work: Attempts, seen: EntrySeen) -> None:
    store = captured_work.store
    before = store.collect(KEY)
    app = CapturedCompletion(captured_work, HoldStore(store.connect), hold, lambda _entry: seen)
    assert app("tasks", "tl-1", KEY.attempt_id).reason == "entry"
    assert store.collect(KEY) == before


@pytest.mark.parametrize("change", [
    "UPDATE reservation SET generation=2",
    "INSERT INTO task_hold(attempt_id,cause_id,reason,held_at) VALUES('attempt','cause','held',10)",
    "UPDATE attempt SET session_conflict=1",
])
def test_captured_completion_reloads_ownership_under_custody(captured_work: Attempts, change: str) -> None:
    store = captured_work.store
    con = store.connect()
    assert con is not None
    before = store.collect(KEY)

    @contextmanager
    def changed(_admission: Admission) -> Generator[None]:
        con.execute(change)
        yield

    app = CapturedCompletion(captured_work, HoldStore(store.connect), changed, lambda _entry: "gone")
    assert app("tasks", "tl-1", KEY.attempt_id).status in ("refused", "conflict")
    assert store.collect(KEY) == before


def test_captured_completion_retries_custody_and_evidence(captured_work: Attempts, monkeypatch: pytest.MonkeyPatch) -> None:
    store = captured_work.store
    app = CapturedCompletion(captured_work, HoldStore(store.connect), hold, lambda _entry: "gone")
    record = store.load(KEY)
    assert record is not None
    with hold(record.admission):
        assert app("tasks", "tl-1", KEY.attempt_id).status == "unavailable"
    before = store.collect(KEY)

    def unreadable(_ref: object) -> str:
        raise attempt.EvidenceError("temporarily unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(captured_work.files, "read", unreadable)
        assert app("tasks", "tl-1", KEY.attempt_id).reason == "evidence"
    assert store.collect(KEY) == before
    assert app("tasks", "tl-1", KEY.attempt_id).reason == "verification"


@pytest.mark.parametrize("phase", ["admitted", "registered"])
def test_captured_completion_refuses_uncaptured_work(
    tmp_path: Path, surroundings: AttemptSurroundings, phase: str,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    con.execute("UPDATE attempt SET phase=?", (phase,))
    app = CapturedCompletion(attempts, HoldStore(lambda: con), hold, lambda _entry: "gone")
    assert app("tasks", "tl-1", KEY.attempt_id).status == "refused"
    assert execution.calls == [] and execution.permits == 0 and attempts.store.collect(KEY) is None
    con.close()


def test_captured_completion_rejects_changed_callback(captured_work: Attempts) -> None:
    store = captured_work.store
    con = store.connect()
    assert con is not None
    con.execute("UPDATE execution SET recovery_callback=NULL")
    before = con.execute("SELECT * FROM execution").fetchall()
    app = CapturedCompletion(captured_work, HoldStore(store.connect), hold, lambda _entry: "gone")
    assert app("tasks", "tl-1", KEY.attempt_id).status == "unavailable"
    assert con.execute("SELECT * FROM execution").fetchall() == before


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


@pytest.mark.parametrize("staged", [False, True])
def test_preauthorized_renewal_uses_current_admission_without_authorizing_again(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, staged: bool,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    recovery_app.clock = attempts.clock = lambda: 100
    renewed = recovery_app.authorize(KEY, OWNER, token="renewed", deadline=200)
    assert renewed.intent is not None
    if staged:
        assert recovery_app.store.execute(renewed.intent, recovery_app.clock).outcome is Outcome.INTENDED

    def forbidden(*_args: object, **_kwargs: object) -> Result:
        raise AssertionError("Saved authorization must be consumed without granting it again")

    monkeypatch.setattr(recovery_app, "authorize", forbidden)
    app = Continuation(recovery_app, attempts, NativeContinuation(attempts, recovery_app.store))
    result = app(KEY, OWNER, intent=renewed.intent)
    assert result.state is State.COMPLETED and execution.permits == 1
    assert execution.calls[0][2] == 100
    current = attempts.store.load(KEY)
    assert current is not None and current.admission.key == KEY and current.admission.deadline == 200
    assert current.session_ref == renewed.intent.session == "saved"
    assert app(KEY, OWNER, intent=renewed.intent).state is State.COMPLETED and execution.permits == 1
    con.close()


@pytest.mark.parametrize("field", ["key", "owner", "generation", "token", "session"])
def test_preauthorization_requires_exact_attempt_owner_and_authority(
    tmp_path: Path, surroundings: AttemptSurroundings, field: str,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    authorized = recovery_app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    expected = authorized.intent.model_copy(update={field: {
        "key": AttemptKey("other", "dispatch", 1), "owner": Identity(pid=40, pgid=40, start="other", boot="boot"),
        "generation": 2, "token": "other", "session": "other",
    }[field]})
    before = list(con.iterdump())
    result = Continuation(recovery_app, attempts, NativeContinuation(attempts, recovery_app.store))(KEY, OWNER, intent=expected)
    assert result.refusal is not None and result.refusal.outcome is Outcome.CHANGED
    assert result.explanation and execution.calls == [] and list(con.iterdump()) == before
    con.close()


@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.GONE, Seen.UNKNOWN])
def test_registered_preauthorization_never_launches_another_worker(
    tmp_path: Path, surroundings: AttemptSurroundings, seen: Seen,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    processes = Processes()
    recovery_app = recovery(con, processes)
    expected = intended(recovery_app.store)
    native = NativeContinuation(attempts, recovery_app.store)
    record = attempts.store.load(KEY)
    assert record is not None and isinstance(native(record.admission, expected), PendingExecution)
    processes.states[WORKER.pid] = seen
    before = list(con.iterdump())
    result = Continuation(recovery_app, attempts, native)(KEY, OWNER, intent=expected)
    assert result.state is (State.LIVE if seen is Seen.ALIVE else State.REFUSED)
    assert execution.permits == 1 and len(execution.calls) == 1 and list(con.iterdump()) == before
    if result.refusal is not None:
        assert result.refusal.outcome is (Outcome.CHANGED if seen is Seen.GONE else Outcome.UNRESOLVED)
    con.close()


@pytest.mark.parametrize("state", [ClaimState.LOST, ClaimState.UNKNOWN])
def test_preauthorization_rechecks_claim_without_permitting_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, state: ClaimState,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    authorized = recovery_app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    recovery_app.claim = lambda _admission: Claim(state=state, explanation="The claim is no longer confirmed.")
    before = list(con.iterdump())
    result = Continuation(recovery_app, attempts, NativeContinuation(attempts, recovery_app.store))(
        KEY, OWNER, intent=authorized.intent,
    )
    assert result.refusal is not None and result.refusal.outcome is (
        Outcome.CLAIM_LOST if state is ClaimState.LOST else Outcome.CLAIM_UNKNOWN)
    assert result.explanation and execution.calls == [] and list(con.iterdump()) == before
    con.close()


def test_renewed_continuation_fences_old_callbacks_and_pending_capture(
    tmp_path: Path, surroundings: AttemptSurroundings,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    recovery_app = recovery(con)
    expected = intended(recovery_app.store)
    record = attempts.store.load(KEY)
    assert record is not None
    native = NativeContinuation(attempts, recovery_app.store)
    old = native(record.admission, expected)
    assert isinstance(old, PendingExecution)
    recovery_app.clock = attempts.clock = lambda: 100
    renewed = recovery_app.authorize(KEY, OWNER, token="renewed", deadline=200)
    assert renewed.intent is not None
    current = attempts.store.load(KEY)
    assert current is not None
    for admission in (record.admission, current.admission):
        with pytest.raises(StoreRefused):
            attempts.store.session(admission, "saved", old.identity)
    app = Continuation(recovery_app, attempts, native)
    stale = app.capture(old)
    assert stale.refusal is not None and stale.refusal.outcome is Outcome.CONFLICT
    assert app(KEY, OWNER, intent=renewed.intent).state is State.COMPLETED and execution.permits == 2
    assert execution.calls[-1][2] == 100
    saved = attempts.store.collect(KEY)
    assert app.capture(old).state is State.REFUSED and attempts.store.collect(KEY) == saved
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
