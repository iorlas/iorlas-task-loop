"""Recovery entry retains custody and claim renewal through execution, capture and completion."""

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from stream_proc import OwnedProcess, ProcessObservation
from test_attempt import AttemptSurroundings
from test_attempt import surroundings as attempt_surroundings
from test_native_continuation import NativeRun, prepared
from test_recovery import recovery
from test_recovery_launch import con as recovery_connection
from test_recovery_store import KEY, OWNER

from taskloop import attempt_entry, slot_lock
from taskloop.attempt import Attempts
from taskloop.attempt_entry import EntryArgs, enter
from taskloop.attempt_types import AttemptKey, CaptureResult, PendingResult, Unsettled
from taskloop.claim_lease import Beat
from taskloop.recovery.continuation_models import State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.entry import RecoveryEntry
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.models import Intent
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.store import RecoveryStore
from taskloop.verifier import Verifier

surroundings = attempt_surroundings
con = recovery_connection
ENTRY_OWNER = OwnedProcess(30, 30, "owner", "boot")


def entry_apps(
    con: sqlite3.Connection, surroundings: AttemptSurroundings, execution: NativeRun,
) -> tuple[Attempts, Continuation, Intent]:
    attempts = prepared(con, surroundings, execution)
    app = recovery(con)
    app.custody = slot_lock.hold
    authorized = app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    return attempts, Continuation(app, attempts, NativeContinuation(attempts, RecoveryStore(lambda: con))), authorized.intent


def run_entry(
    tmp_path: Path, attempts: Attempts, continuation: Continuation, lines: list[str], beat: Callable[[], Beat],
    *, identity: OwnedProcess = ENTRY_OWNER,
) -> int:
    def heartbeat(root: str, task: str) -> Callable[[], Beat]:
        assert (root, task) == ("/tracker", "tl-1")
        return beat

    return enter(EntryArgs(tmp_path / "factory.db", tmp_path, 600, "tasks", "tl-1"), lambda _db, _root: attempts,
                 lambda _pid: ProcessObservation("matching", identity), lambda: 10, lambda _seconds: None, lines.append,
                 lambda _worker: True, heartbeat, threading.Event(), lambda _root, _task: True, attempts.checkouts,
                 lambda: continuation)


@pytest.mark.parametrize("busy_capture", [False, True])
def test_saved_owner_continues_under_custody_and_a_renewed_claim(
    con: sqlite3.Connection, surroundings: AttemptSurroundings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, busy_capture: bool,
) -> None:
    execution = NativeRun()
    attempts, continuation, intent = entry_apps(con, surroundings, execution)
    columns = "attempt_id,dispatch_token,generation,entry_pid,entry_start,entry_boot,session_ref"
    before = con.execute(f"SELECT {columns} FROM attempt").fetchone()
    reservation = con.execute("SELECT * FROM reservation").fetchall()
    beats: list[str] = []
    verified: list[AttemptKey] = []
    capture = attempts.capture
    captures: list[PendingResult] = []

    def busy(pending: PendingResult, callback: Callback | None = None) -> CaptureResult:
        captures.append(pending)
        return CaptureResult("unavailable", "store") if len(captures) < 3 else capture(pending, callback)

    if busy_capture:
        monkeypatch.setattr(attempts, "capture", busy)

    def held() -> None:
        assert beats == ["held"]
        record = attempts.store.load(KEY)
        assert record is not None
        with pytest.raises(slot_lock.SlotBusy), slot_lock.hold(record.admission):
            raise AssertionError("Entry released custody")

    def verify(_self: Verifier, key: AttemptKey) -> Unsettled:
        held()
        stored = attempts.store.collect(key)
        assert stored is not None and stored.answer.kind == "valid" and stored.session_state == "complete"
        verified.append(key)
        return Unsettled("uncommitted")

    def beat() -> Beat:
        beats.append("held")
        return "held"

    execution.after_start = held
    monkeypatch.setattr(attempt_entry.Verifier, "verify", verify)
    lines: list[str] = []
    assert run_entry(tmp_path, attempts, continuation, lines, beat) == 1
    assert execution.permits == 1 and verified == [KEY] and "claim=held" in lines[0], lines
    assert "saved" in execution.calls[0][1].argv
    assert con.execute(f"SELECT {columns} FROM attempt").fetchone() == before
    assert con.execute("SELECT * FROM reservation").fetchall() == reservation
    assert intent.entry == (7, "entry", "boot")


@pytest.mark.parametrize("refusal", ["identity", "revision", "session", "claim_lost", "claim_fault"])
def test_changed_authority_and_failed_initial_renewal_run_no_harness(
    con: sqlite3.Connection, surroundings: AttemptSurroundings, tmp_path: Path, refusal: str,
) -> None:
    execution = NativeRun()
    attempts, continuation, _intent = entry_apps(con, surroundings, execution)

    def beat() -> Beat:
        if refusal == "revision":
            con.execute("UPDATE attempt SET rev=rev+1")
        if refusal == "session":
            con.execute("UPDATE attempt SET session_ref='different'")
        if refusal == "claim_fault":
            raise RuntimeError("renewal unavailable")
        return "lost" if refusal == "claim_lost" else "held"

    lines: list[str] = []
    identity = OwnedProcess(30, 30, "different" if refusal == "identity" else "owner", "boot")
    assert run_entry(tmp_path, attempts, continuation, lines, beat, identity=identity) == 1
    assert execution.permits == 0 and execution.calls == [] and lines
    assert attempts.store.collect(KEY) is None


@pytest.mark.parametrize("ending", ["accepted", "conflict", "deadline"])
def test_capture_retries_the_same_execution_without_another_harness(
    con: sqlite3.Connection, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, ending: str,
) -> None:
    execution = NativeRun()
    attempts, continuation, intent = entry_apps(con, surroundings, execution)
    capture = attempts.capture
    seen: list[PendingResult] = []
    identities: list[Callback | None] = []
    now = [10.0]

    def busy(pending: PendingResult, callback: Callback | None = None) -> CaptureResult:
        seen.append(pending)
        identities.append(callback)
        if len(seen) < 3:
            return CaptureResult("unavailable", "store")
        return CaptureResult("conflict", "changed") if ending == "conflict" else capture(pending, callback)

    def wait(_seconds: float) -> None:
        now[0] = 100 if ending == "deadline" else now[0] + 2

    monkeypatch.setattr(attempts, "capture", busy)
    record = attempts.store.load(KEY)
    assert record is not None
    with slot_lock.hold(record.admission):
        result = RecoveryEntry(continuation).run(intent, OWNER, lambda: now[0], wait, 2)
    expected = {"accepted": State.COMPLETED, "conflict": State.REFUSED, "deadline": State.PENDING_CAPTURE}
    assert result.state is expected[ending] and execution.permits == 1 and len(execution.calls) == 1
    assert all(value is seen[0] for value in seen) and all(value == identities[0] for value in identities)
    assert len(seen) == (1 if ending == "deadline" else 3)
    assert (attempts.store.collect(KEY) is not None) == (ending == "accepted")
