"""Execution and registration share a runtime allowance, independent of epoch changes."""

from dataclasses import dataclass

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.testing import FakeRun
from test_attempt import ENTRY, KEY, WORKER, AttemptSurroundings, CountingHarness, database, fake
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_store import AttemptStore

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


def test_runtime_timeout_after_registration_is_captured_and_collected_once(
    surroundings: AttemptSurroundings, cleanups: list[int],
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
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == "run:timeout"
    assert con.execute("SELECT rc,timed_out FROM execution").fetchone() == (-15, 1)
    assert attempts.collect(KEY) == result and attempts.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1 and cleanups == [1]
