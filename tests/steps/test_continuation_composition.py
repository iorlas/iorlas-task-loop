"""Production continuation connects native observations, bounded registration and shared custody."""

from contextlib import nullcontext
from pathlib import Path

import pytest
from test_attempt import AttemptSurroundings, codex
from test_attempt import surroundings as attempt_surroundings
from test_native_continuation import NativeRun, prepared
from test_recovery import Processes
from test_recovery_store import KEY, OWNED, OWNER, database

from taskloop import composition, slot_lock
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, Admission
from taskloop.git_views import GitViews
from taskloop.recovery.continuation_models import State
from taskloop.recovery.models import Claim
from taskloop.recovery.native import NativeContinuation

surroundings = attempt_surroundings


@pytest.mark.parametrize("already_held", [False, True])
def test_real_composition_retains_custody_through_native_execution(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, already_held: bool,
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

    def held_during_execution() -> None:
        with pytest.raises(slot_lock.SlotBusy), slot_lock.hold(admission):
            raise AssertionError("Slot custody was released before execution returned")

    execution.after_start = held_during_execution
    app = composition.open_continuation(path, tmp_path, GitViews(DEFAULT_GIT_READ_SECONDS), claim, codex)
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
