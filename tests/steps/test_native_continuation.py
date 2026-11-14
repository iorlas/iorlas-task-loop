"""Native continuation uses saved admission and registration-bound output hooks."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from any_agent import CodexHarness, Harness, LaunchSpec, RunHooks, RunOutcome
from any_agent.procs import Worker
from test_attempt import AttemptSurroundings
from test_attempt import surroundings as attempt_surroundings
from test_recovery import recovery
from test_recovery_callbacks import raw
from test_recovery_store import KEY, OWNER, database

from taskloop.attempt import Attempts, Execution
from taskloop.attempt_store import AttemptStore
from taskloop.command_sink import WatchedHooks
from taskloop.duration_evidence import DurationSample, DurationState
from taskloop.evidence_files import EvidenceFiles
from taskloop.recovery.callbacks import PendingExecution
from taskloop.recovery.continuation_models import State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.models import Outcome, Snapshot
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore

surroundings = attempt_surroundings
WORKER = Worker(pid=80, pgid=81, start="continued", boot="boot")


@dataclass
class NativeRun:
    calls: list[tuple[Harness, LaunchSpec, float, RunHooks | None]] = field(default_factory=list)
    permits: int = 0
    before_start: Callable[[], None] | None = None
    after_start: Callable[[], None] | None = None

    def __call__(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.calls.append((harness, spec, timeout, hooks))
        assert hooks is not None and hooks.started is not None and hooks.ref is not None
        if self.before_start is not None:
            self.before_start()
        hooks.started(WORKER)
        self.permits += 1
        hooks.ref("saved")
        if self.after_start is not None:
            self.after_start()
        return raw(WORKER)


def prepared(con: sqlite3.Connection, surroundings: AttemptSurroundings, execution: Execution) -> Attempts:
    app = surroundings.attempts(AttemptStore(lambda: con), execution)
    ref = app.files.put_input(KEY, "Continue the saved task")
    con.execute("UPDATE attempt SET input_path=?,input_digest=?", (ref.path, ref.digest))
    con.execute("UPDATE slot SET path=?", (str(surroundings.tmp / "continued-slot"),))
    return app


def test_native_resume_preserves_admission_and_cleans_once(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    cleanups: list[Harness] = []

    def cleaned(harness: Harness) -> None:
        cleanups.append(harness)

    monkeypatch.setattr(CodexHarness, "cleanup", cleaned)
    result = Continuation(recovery(con), attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))(KEY, OWNER)
    assert result.state is State.COMPLETED and result.completion is not None
    assert result.completion.execution is not None and result.completion.execution.answer.kind == "valid"
    assert execution.permits == 1 and len(execution.calls) == 1
    harness, spec, timeout, hooks = execution.calls[0]
    assert spec.argv[1:3] == ["exec", "resume"] and "saved" in spec.argv
    assert "chosen" in spec.argv and "Continue the saved task" in (spec.stdin or "")
    assert spec.cwd == str(surroundings.tmp / "continued-slot") and timeout == 90
    assert isinstance(hooks, WatchedHooks) and hooks.before_stop is not None and hooks.after_stop is not None
    assert cleanups == [harness]
    saved = attempts.store.callback(KEY)
    assert saved is not None and saved.worker.pid == WORKER.pid and saved.generation == 1
    con.close()


def test_native_result_is_bound_before_capture(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    app = recovery(con)
    authorized = app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    intended = app.store.execute(authorized.intent, lambda: 10)
    assert intended.intent is not None
    record = attempts.store.load(KEY)
    assert record is not None
    now = [1000.0]
    attempts.monotonic = lambda: now[0]
    ordinary = attempts.files.observe_duration(KEY, attempts.monotonic)
    now[0] += 4
    ordinary.seal()
    earlier = attempts.files.duration(KEY)
    now[0] = 9000  # continuation gets its own origin, without restart downtime

    def advanced() -> None:
        now[0] += 3

    execution.after_start = advanced
    result = NativeContinuation(attempts, app.store)(record.admission, intended.intent)
    assert isinstance(result, PendingExecution)
    snapshot = app.store.snapshot(KEY, 10)
    assert isinstance(snapshot, Snapshot) and snapshot.intent is not None
    assert result.identity == callback(snapshot.intent)
    assert result.result.sessions.fault is None and attempts.store.collect(KEY) is None
    duration = EvidenceFiles(tmp_path).duration(KEY, result.identity)
    assert duration is not None and duration.state is DurationState.SEALED
    assert duration.elapsed == 3 and duration.command_offset is None
    assert attempts.files.duration(KEY) == earlier
    next_execution = intended.intent.model_copy(update={"generation": 2, "token": "new-token"})
    assert attempts.files.duration(KEY, next_execution) is None
    attempts.files.observe_duration(KEY, attempts.monotonic, next_execution).seal()
    assert attempts.files.duration(KEY, next_execution) != duration
    assert attempts.files.duration(KEY, result.identity) == duration
    con.close()


@pytest.mark.parametrize("change", ["UPDATE attempt SET rev=rev+1", "INSERT INTO drain_state VALUES(1,1,'draining')"])
def test_registration_revalidates_before_permit_and_cleans_on_refusal(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)

    def changed() -> None:
        con.execute(change)

    cleanups: list[Harness] = []

    def cleaned(harness: Harness) -> None:
        cleanups.append(harness)

    monkeypatch.setattr(CodexHarness, "cleanup", cleaned)
    execution.before_start = changed
    result = Continuation(recovery(con), attempts, NativeContinuation(attempts, RecoveryStore(lambda: con)))(KEY, OWNER)
    assert result.refusal is not None and result.refusal.outcome is Outcome.UNAVAILABLE
    assert len(execution.calls) == 1 and execution.permits == 0 and len(cleanups) == 1
    assert attempts.store.collect(KEY) is None
    con.close()


@pytest.mark.parametrize("failure", ["write", "invalid_clock", "execution"])
def test_continuation_duration_failures_preserve_execution_and_cleanup(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    con = database(tmp_path / "factory.db")
    execution = NativeRun()
    attempts = prepared(con, surroundings, execution)
    app = recovery(con)
    authorized = app.authorize(KEY, OWNER)
    assert authorized.intent is not None
    intended = app.store.execute(authorized.intent, lambda: 10)
    assert intended.intent is not None
    record = attempts.store.load(KEY)
    assert record is not None
    now = [1000.0]
    attempts.monotonic = lambda: now[0]
    cleanups: list[Harness] = []

    def cleaned(harness: Harness) -> None:
        cleanups.append(harness)

    def write(_files: EvidenceFiles, _key: object, _sample: DurationSample, _execution: object = None) -> None:
        raise OSError("duration evidence full")

    def finished() -> None:
        now[0] = float("nan") if failure == "invalid_clock" else 1003
        if failure == "execution":
            raise RuntimeError("execution lost without live callbacks")

    monkeypatch.setattr(CodexHarness, "cleanup", cleaned)
    if failure == "write":
        monkeypatch.setattr(EvidenceFiles, "write_duration", write)
    execution.after_start = finished
    result = NativeContinuation(attempts, app.store)(record.admission, intended.intent)
    assert execution.permits == 1 and len(execution.calls) == len(cleanups) == 1
    assert attempts.store.collect(KEY) is None
    if failure == "execution":
        assert not isinstance(result, PendingExecution) and result.outcome is Outcome.UNAVAILABLE
        duration = attempts.files.duration(KEY, intended.intent)
        assert duration is not None and duration.state is DurationState.SEALED and duration.elapsed == 3
    else:
        assert isinstance(result, PendingExecution) and result.result.sessions.fault is None
        assert attempts.files.duration(KEY, intended.intent) is None
    con.close()
