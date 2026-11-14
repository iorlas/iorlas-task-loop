"""Execution and registration share a runtime allowance, independent of epoch changes."""

from dataclasses import dataclass

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary, events
from any_agent.testing import FakeRun
from test_attempt import ENTRY, KEY, WORKER, AttemptSurroundings, CountingHarness, database, fake
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.clock_jumps import ClockContext, ClockDirection, ClockJump
from taskloop.command_sink import WatchedHooks
from taskloop.duration_evidence import DurationSample, DurationState
from taskloop.evidence_files import EvidenceFiles

surroundings = attempt_surroundings


@dataclass
class Clock:
    wall: float = 10
    runtime: float = 1000

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.runtime


@pytest.fixture
def cleanups(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr("taskloop.agents.launch.CodexHarness", CountingHarness)
    monkeypatch.setattr(CountingHarness, "cleanups", calls)
    monkeypatch.setattr(CountingHarness, "broken", False)
    return calls


@pytest.mark.parametrize("jump", [7200, -7200])
def test_epoch_jumps_during_handoff_and_registration_preserve_allowance(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, cleanups: list[int], jump: float,
) -> None:
    con, clock = database(surroundings), Clock()
    store, execution = AttemptStore(lambda: con), fake(refs=("session",))
    warm = store.warm

    def handoff() -> None:
        warm()
        clock.wall += jump
        clock.runtime += 7

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert timeout == 83
        clock.wall -= jump * 2
        clock.runtime += 3
        return execution(harness, spec, timeout, hooks)

    monkeypatch.setattr(store, "warm", handoff)
    attempts = surroundings.attempts(store, run, clock=clock.time, monotonic=clock.monotonic)
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "verification"
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert con.execute("SELECT deadline,worker_pid,session_ref FROM attempt").fetchone() == (100, WORKER.pid, "session")
    assert con.execute("SELECT timed_out FROM execution").fetchone() == (0,)
    assert attempts.collect(KEY) == result and attempts.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1 and cleanups == [1]


@pytest.mark.parametrize("elapsed", [90, 91])
def test_runtime_exhausted_during_handoff_never_disables_timeout(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, cleanups: list[int], elapsed: float,
) -> None:
    con, clock = database(surroundings), Clock()
    store, execution = AttemptStore(lambda: con), fake()
    warm = store.warm

    def handoff() -> None:
        warm()
        clock.wall -= 7200
        clock.runtime += elapsed

    monkeypatch.setattr(store, "warm", handoff)
    result = surroundings.attempts(store, execution, clock=clock.time, monotonic=clock.monotonic).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "expired")
    assert execution.calls == [] and cleanups == [1]
    assert con.execute("SELECT phase,worker_pid FROM attempt").fetchone() == ("dispatching", None)
    assert con.execute("SELECT count(*) FROM execution").fetchone() == (0,)


def test_runtime_exhausted_at_registration_refuses_before_session_or_capture(
    surroundings: AttemptSurroundings, cleanups: list[int],
) -> None:
    con, clock = database(surroundings), Clock()
    execution = fake(refs=("session",))

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert timeout == 90
        clock.wall -= 7200
        clock.runtime += timeout
        return execution(harness, spec, timeout, hooks)

    result = surroundings.attempts(AttemptStore(lambda: con), run, clock=clock.time, monotonic=clock.monotonic).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "expired")
    assert con.execute("SELECT phase,worker_pid,session_ref FROM attempt").fetchone() == ("dispatching", None, None)
    assert con.execute("SELECT count(*) FROM execution").fetchone() == (0,)
    assert cleanups == [1]


@pytest.mark.parametrize("broken", [False, True])
def test_runtime_timeout_after_registration_is_captured_and_collected_once(
    surroundings: AttemptSurroundings, cleanups: list[int], broken: bool,
) -> None:
    con, clock = database(surroundings), Clock()
    execution = FakeRun(RunOutcome(rc=-15, timed_out=True, worker=WORKER, summary=Summary(rc=-15)))

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert timeout == 90
        outcome = execution(harness, spec, timeout, hooks)
        clock.wall -= 7200
        clock.runtime += timeout
        return outcome

    attempts = surroundings.attempts(AttemptStore(lambda: con), run, clock=clock.time, monotonic=clock.monotonic)
    path = attempts.files.clock_jumps_path(KEY)
    if broken:
        path.mkdir(parents=True)  # a clock evidence write fails independently of the execution capture
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "run:timeout"
    assert con.execute("SELECT rc,timed_out FROM execution").fetchone() == (-15, 1)
    assert attempts.collect(KEY) == result and attempts.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1 and cleanups == [1]
    if broken:
        assert path.is_dir()
    else:
        records = [ClockJump.model_validate_json(line) for line in path.read_text().splitlines()]
        assert [(record.context, record.direction, record.difference) for record in records] == [
            (ClockContext.ACTIVE, ClockDirection.BACKWARD, -7290),
        ]


@pytest.mark.parametrize("broken", [False, True])
def test_active_jumps_survive_lost_activity_and_clock_evidence_without_changing_runtime(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, cleanups: list[int], broken: bool,
) -> None:
    con, clock = database(surroundings), Clock()
    execution = fake(refs=("session",))
    records: list[ClockJump] = []
    append = EvidenceFiles.append_clock_jump

    def write(files: EvidenceFiles, key: AttemptKey, jump: ClockJump) -> None:
        records.append(jump)
        if broken:
            raise OSError("clock evidence full")
        append(files, key, jump)

    def lost_activity(_files: EvidenceFiles, _key: AttemptKey) -> None:
        raise OSError("activity full")

    def advance(difference: float) -> None:
        clock.runtime += 2
        clock.wall += 2 + difference

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert timeout == 90 and isinstance(hooks, WatchedHooks)
        outcome = execution(harness, spec, timeout, hooks)
        advance(7200)
        hooks.live.started(WORKER.pid)
        advance(-14400)
        hooks.live.feed(events.Msg(text="thinking"))
        advance(7200)
        hooks.live.poll(2)
        advance(0)
        hooks.live.poll(2)
        advance(-7200)
        hooks.live.end("done")
        advance(7200)  # no further callbacks: the return boundary must observe this jump
        return outcome

    monkeypatch.setattr(EvidenceFiles, "append_clock_jump", write)
    monkeypatch.setattr(EvidenceFiles, "open_events", lost_activity)
    attempts = surroundings.attempts(AttemptStore(lambda: con), run, clock=clock.time, monotonic=clock.monotonic)
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "verification"
    assert attempts.collect(KEY) == result and attempts.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1 and cleanups == [1]
    assert con.execute("SELECT timed_out FROM execution").fetchone() == (0,)
    assert [record.difference for record in records] == [7200, -14400, 7200, -7200, 7200]
    assert all(record.context == ClockContext.ACTIVE and record.monotonic_elapsed == 2 for record in records)
    path = attempts.files.clock_jumps_path(KEY)
    if broken:
        assert not path.exists()
    else:
        assert [ClockJump.model_validate_json(line) for line in path.read_text().splitlines()] == records
    assert not attempts.files.events_path(KEY).exists()
    duration = EvidenceFiles(surroundings.tmp).duration(KEY)
    assert duration is not None and duration.state is DurationState.SEALED
    assert duration.elapsed == 12 and duration.command_offset is None


@pytest.mark.parametrize("difference", [7200, -7200])
def test_an_eventless_failed_run_still_records_its_final_clock_jump(
    surroundings: AttemptSurroundings, cleanups: list[int], difference: float,
) -> None:
    con, clock = database(surroundings), Clock()

    def run(_harness: Harness, _spec: LaunchSpec, timeout: float, _hooks: RunHooks | None) -> RunOutcome:
        assert timeout == 90
        clock.wall += difference + 3
        clock.runtime += 3
        raise RuntimeError("execution lost")

    attempts = surroundings.attempts(AttemptStore(lambda: con), run, clock=clock.time, monotonic=clock.monotonic)
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "run_failed:RuntimeError" and cleanups == [1]
    records = [ClockJump.model_validate_json(line) for line in attempts.files.clock_jumps_path(KEY).read_text().splitlines()]
    assert [record.difference for record in records] == [difference]
    assert not attempts.files.events_path(KEY).exists()
    duration = EvidenceFiles(surroundings.tmp).duration(KEY)
    assert duration is not None and duration.state is DurationState.SEALED
    assert duration.elapsed == 3 and duration.command_offset is None


@pytest.mark.parametrize("failure", ["write", "final_write", "regression", "nonfinite", "clock_exception"])
def test_duration_evidence_failures_preserve_result_registration_and_cleanup(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, cleanups: list[int], failure: str,
) -> None:
    con, clock = database(surroundings), Clock()
    execution = fake(refs=("session",))
    broken = False
    write_duration = EvidenceFiles.write_duration

    def monotonic() -> float:
        if broken and failure == "clock_exception":
            raise RuntimeError("clock lost")
        return clock.runtime

    def write(files: EvidenceFiles, key: AttemptKey, sample: DurationSample, _execution: object = None) -> None:
        if failure == "write" or sample.state is DurationState.SEALED:
            raise OSError("duration full")
        write_duration(files, key, sample)

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        nonlocal broken
        assert timeout == 90 and isinstance(hooks, WatchedHooks)
        outcome = execution(harness, spec, timeout, hooks)
        broken = True
        clock.runtime = float("nan") if failure == "nonfinite" else 999 if failure == "regression" else 1004
        hooks.live.feed(events.Cmd(id="1", text="just check"))
        return outcome

    if failure in ("write", "final_write"):
        monkeypatch.setattr(EvidenceFiles, "write_duration", write)
    attempts = surroundings.attempts(AttemptStore(lambda: con), run, clock=clock.time, monotonic=monotonic)
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "verification" and attempts.collect(KEY) == result
    assert cleanups == [1] and len(execution.calls) == 1
    assert con.execute("SELECT timed_out FROM execution").fetchone() == (0,)
    assert con.execute("SELECT worker_pid FROM attempt").fetchone() == (WORKER.pid,)
    duration = attempts.files.duration(KEY)
    if failure == "final_write":
        assert duration is not None and duration.state is DurationState.ACTIVE
        assert duration.elapsed == duration.command_offset == 4
    else:
        assert duration is None
