"""Production continuation connects native observations, bounded registration and shared custody."""

from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

import pytest
from stream_proc import OwnedProcess
from test_attempt import AttemptSurroundings, codex
from test_attempt import surroundings as attempt_surroundings
from test_continuation import captured_work as captured_attempt
from test_launch import FakeStart
from test_native_continuation import NativeRun, prepared
from test_recovery import Processes
from test_recovery_store import KEY, OWNED, OWNER, database

from taskloop import composition, slot_lock
from taskloop.attempt import Attempts
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, Admission
from taskloop.git_views import GitViews
from taskloop.launch import Launched
from taskloop.recovery.continuation_models import State
from taskloop.recovery.entry import RecoveryEntry
from taskloop.recovery.models import Claim, Intent
from taskloop.recovery.native import NativeContinuation

surroundings = attempt_surroundings
captured_work = captured_attempt


def test_production_launch_and_entry_share_the_saved_authorization(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    con.execute("PRAGMA journal_mode=WAL")
    execution = NativeRun()
    prepared(con, surroundings, execution)
    con.close()
    processes = Processes()
    start = FakeStart(identity=OwnedProcess(OWNER.pid, OWNER.pgid, OWNER.start, OWNER.boot))
    roots: list[Path] = []

    def bound(root: Path) -> Callable[[Admission], Claim]:
        roots.append(root)
        return lambda _admission: OWNED

    monkeypatch.setattr(composition, "NativeProcesses", lambda: processes)
    monkeypatch.setattr(composition, "tracker_recovery_claim", bound)
    monkeypatch.setattr(composition, "popen_registered", start)
    monkeypatch.setattr(composition.time, "time", lambda: 10)
    monkeypatch.setattr(composition, "run", lambda harness, spec, timeout, hooks, **_kwargs: execution(harness, spec, timeout, hooks))
    views = GitViews(DEFAULT_GIT_READ_SECONDS)
    assert isinstance(composition.open_launcher(path, tmp_path, views).launch("tasks", "tl-1", 30), Launched)
    app = composition.open_continuation(path, tmp_path, views, credentials=codex)
    entry = RecoveryEntry(app)
    intent = entry.registered(KEY, (OWNER.pid, OWNER.start, OWNER.boot))
    assert isinstance(intent, Intent)
    record = app.attempts.store.load(KEY)
    assert record is not None and record.admission.deadline == 1810
    with slot_lock.hold(record.admission):
        result = entry.run(intent, OWNER, lambda: 10, lambda _seconds: None, 2)
    assert result.state is State.COMPLETED and execution.permits == 1 and roots == [Path("/tracker"), Path("/tracker")]
    assert intent.entry == record.admission.entry == (7, "entry", "boot") and "saved" in execution.calls[0][1].argv


@pytest.mark.parametrize("already_held", [False, True])
@pytest.mark.parametrize("bound_claim", [False, True])
def test_real_composition_retains_custody_through_native_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, already_held: bool, bound_claim: bool,
) -> None:
    path = tmp_path / "factory.db"
    con = database(path)
    execution = NativeRun()
    seeded = prepared(con, surroundings, execution)
    record = seeded.store.load(KEY)
    assert record is not None
    admission = record.admission
    con.close()
    processes = Processes()
    monkeypatch.setattr(composition, "NativeProcesses", lambda: processes)
    monkeypatch.setattr(composition.time, "time", lambda: 10)
    monkeypatch.setattr(composition, "run", lambda harness, spec, timeout, hooks, **_kwargs: execution(harness, spec, timeout, hooks))
    claims: list[Admission] = []

    def claim(value: Admission) -> Claim:
        claims.append(value)
        return OWNED

    def bound(root: Path) -> Callable[[Admission], Claim]:
        assert root == Path("/tracker")
        return claim

    monkeypatch.setattr(composition, "tracker_recovery_claim", bound)

    def held_during_execution() -> None:
        with pytest.raises(slot_lock.SlotBusy), slot_lock.hold(admission):
            raise AssertionError("Slot custody was released before execution returned")

    execution.after_start = held_during_execution
    app = composition.open_continuation(path, tmp_path, GitViews(DEFAULT_GIT_READ_SECONDS), None if bound_claim else claim, codex)
    assert isinstance(app.native, NativeContinuation)
    registration = app.native.registration.connect()
    normal = app.recovery.store.connect()
    assert registration is not None and normal is not None and registration is not normal
    assert registration.execute("PRAGMA busy_timeout").fetchone() == (1500,)
    assert normal.execute("PRAGMA busy_timeout").fetchone() == (5000,)
    with slot_lock.hold(admission) if already_held else nullcontext():
        result = app(KEY, OWNER, custody=nullcontext() if already_held else None)
    assert result.state is State.COMPLETED and claims == [admission] and execution.permits == 1
    assert app(KEY, OWNER).state is State.COMPLETED and execution.permits == 1


@pytest.mark.parametrize("pending", ["answer", "pending", "fault"])
def test_real_completion_finishes_captured_work_after_reopen(
    tmp_path: Path, surroundings: AttemptSurroundings, captured_work: Attempts, pending: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = captured_work.store.connect()
    assert con is not None
    if pending != "answer":
        assert captured_work.execute(KEY, (7, "entry", "boot")).reason == "verification"
        con.execute("UPDATE execution SET session_state=?", (pending,))
        con.execute("UPDATE attempt SET session_ref=NULL")
    record = captured_work.store.load(KEY)
    assert record is not None
    reservations = con.execute("SELECT * FROM reservation").fetchall()
    identity = con.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall()
    con.close()

    def no_execution(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Captured work must complete without executing a harness")

    def stopped(_entry: object) -> str:
        with pytest.raises(slot_lock.SlotBusy), slot_lock.hold(record.admission):
            raise AssertionError("Completion must retain slot custody")
        return "gone"

    monkeypatch.setattr(composition, "run", no_execution)
    monkeypatch.setattr(composition, "entry_seen", stopped)
    app = composition.open_completion(tmp_path / "factory.db", surroundings.tmp, GitViews(DEFAULT_GIT_READ_SECONDS))
    reopened = app.attempts.store.connect()
    assert reopened is not None and reopened is not con
    try:
        before = app.attempts.store.collect(KEY)
        assert before is not None
        if pending == "answer":
            assert before.answer.kind == "validation_pending"
        else:
            assert before.answer.kind == "valid" and before.session_state == pending
        result = app("tasks", "tl-1", KEY.attempt_id)
        assert result.status == "pending" and result.reason == "verification"
        assert result.execution is not None
        assert result.execution.answer.kind == "valid" and result.execution.session_state == "complete"
        assert app("tasks", "tl-1", KEY.attempt_id) == result
        assert app.attempts.store.collect(KEY) == result.execution
        assert reopened.execute("SELECT * FROM reservation").fetchall() == reservations
        assert reopened.execute("SELECT attempt_id,dispatch_token,generation FROM attempt").fetchall() == identity
        assert reopened.execute("SELECT session_ref FROM attempt").fetchone() == ("saved",)
    finally:
        reopened.close()
