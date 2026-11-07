"""Pipeline waits book shared-resource time and stop with typed outcomes, using only fakes."""
import contextlib
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from support.narrow_hosts import FakeWaitsHost

from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.pipeline.waits import Waits
from taskloop.contracts import log as rec
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.kinds import Kind
from taskloop.domain.lanes.liveness import LIVENESS


def test_wait_books_seconds_outside_the_budget():
    host = FakeWaitsHost()
    host.fake_clock.advance(180)
    waits = Waits(host)
    wid = waits.start(WaitWhat.CHECK_SLOT)
    waits.add(120, WaitWhat.CHECK_SLOT, wid)
    assert host.budget.waited == 120
    assert host.budget.spent_min() == 1
    rows = [item.rec for item in host.stores.run_log("run").read_from(0).items]
    ended = [row for row in rows if isinstance(row, rec.WaitEnd)]
    assert len(ended) == 1
    assert ended[0].id == wid
    assert ended[0].wait_seconds == 120
    assert not ended[0].in_budget


def test_wait_cannot_book_more_than_elapsed_time():
    host = FakeWaitsHost()
    host.fake_clock.advance(30)
    Waits(host).add(120, WaitWhat.CHECK_SLOT)
    assert host.budget.waited == 30
    assert host.budget.spent_min() == 0


def test_lock_deadline_pauses_lane_and_books_wait(monkeypatch):
    host = FakeWaitsHost()

    @contextlib.contextmanager
    def busy(
        path: Path | str, holder: str, waiting: Callable[[str], None] | None = None, *,
        timeout: float | None = None, check: Callable[[], None] | None = None,
    ) -> Generator[None]:
        assert timeout == LIVENESS.lock_wait_s
        assert waiting is not None
        assert check is not None
        check()
        waiting("holder")
        host.fake_clock.advance(timeout)
        raise TimeoutError("holder")
        yield

    monkeypatch.setattr(host, "os_lock", busy)
    with pytest.raises(Blocked, match="wait deadline exceeded") as stopped, Waits(host).locked("land_lock", host.log_path):
        pytest.fail("acquired a busy lock")
    assert stopped.value.kind is Kind.PAUSE_LANE
    assert host.waited == LIVENESS.lock_wait_s
    assert host.halted == ["halt"]
    rows = [item.rec for item in host.stores.run_log("run").read_from(0).items]
    assert sum(isinstance(row, rec.WaitEnd) for row in rows) == 1


def test_over_budget_raises_budget_ask(monkeypatch):
    host = FakeWaitsHost()
    host.budget.charge(float(host.cfg.budget_usd) + 1)
    monkeypatch.setattr("taskloop.app.pipeline.waits.outcomes.run_breakdown", lambda *_: [])
    with pytest.raises(Blocked, match="over budget") as stopped:
        Waits(host).budget_check()
    assert stopped.value.kind is Kind.ASK_BUDGET
    assert stopped.value.spec is not None
