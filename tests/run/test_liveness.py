"""Wall deadlines and bounded lock waits survive slow or hung work."""

import contextlib
from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from support.fake_deadline import FakeDeadline
from support.lifecycle import lifecycle
from support.narrow_hosts import FakeWaitsHost

from taskloop.adapters import deadline
from tlkernel import log as rec
from tlkernel.config import EngineConfig
from tlkernel.kinds import Kind
from tlkernel.lanesliveness import LIVENESS
from tlpipeline.api import Blocked, Waits
from tltestkit.case import Case


class RunDeadline(Case):
    def test_deadline_parks_and_still_closes_a_hung_run(self):
        host = SimpleNamespace(store=None, bead="b", env=mock.Mock(), checkpoints=mock.Mock(), dead=None,
                               Blocked=Blocked, moved=False, cfg=EngineConfig(run_deadline_min=0.02 / 60))
        once = lifecycle(host)
        timer = FakeDeadline()
        with timer.patched(), mock.patch.object(once, "body", side_effect=lambda *a: timer.wait(0.5)), \
                mock.patch.object(once, "close_out") as close:
            assert once.go() == 2
        assert close.call_args.args[1].outcome.kind is Kind.OWNER_PARK
        assert "deadline" in close.call_args.args[1].outcome.detail


    def test_a_run_longer_than_twenty_minutes_is_not_parked_while_the_profile_allows_it(self):
        assert EngineConfig().run_deadline_min == 45
        host = SimpleNamespace(store=None, bead="b", env=mock.Mock(), checkpoints=mock.Mock(), dead=None,
                               Blocked=Blocked, moved=False, cfg=EngineConfig())
        once = lifecycle(host)
        seen: list[float] = []
        def timed(secs: float, what: str) -> contextlib.AbstractContextManager[None]:
            seen.append(secs)
            return contextlib.nullcontext()
        with mock.patch.object(once, "deadline", side_effect=timed), \
                mock.patch.object(once, "body"), mock.patch.object(once, "close_out"):
            once.go()
        assert seen == [45 * 60]


class LockWait(Case):
    def test_lock_wait_has_finite_timeout_and_a_transient_stop(self):
        host = FakeWaitsHost()
        waits = Waits(host, deadline)

        @contextlib.contextmanager
        def busy(path: Path | str, holder: str, waiting: Callable[[str], None] | None = None,
                 timeout: float | None = None, check: Callable[[], None] | None = None) -> Generator[Path | str]:
            assert timeout is not None
            assert waiting is not None
            assert timeout == LIVENESS.lock_wait_s
            waiting("holder")
            host.fake_clock.advance(timeout)
            raise TimeoutError("holder")
            yield path

        with mock.patch.object(host, "os_lock", busy), pytest.raises(Blocked) as stopped, waits.locked("land_lock", "lock"):
            pytest.fail("acquired a busy lock")
        assert stopped.value.kind is Kind.PAUSE_LANE
        rows = [row.rec for row in host.stores.run_log("run").read_from(0).items]
        assert sum(isinstance(row, rec.WaitEnd) for row in rows) == 1
        assert host.waited == LIVENESS.lock_wait_s
