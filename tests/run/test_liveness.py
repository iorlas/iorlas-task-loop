"""Wall deadlines and bounded lock waits survive slow or hung work."""
import contextlib
from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support.case import Case
from support.fake_deadline import FakeDeadline
from support.narrow_hosts import FakeWaitsHost

from taskloop.app.run.blocked import Blocked
from taskloop.app.run.run_once import RunOnce
from taskloop.app.run.waits import Waits
from taskloop.contracts import log as rec
from taskloop.contracts.kinds import Kind
from taskloop.domain.lanes.liveness import LIVENESS, LivenessCaps


class RunDeadline(Case):
    def test_deadline_parks_and_still_closes_a_hung_run(self):
        host = SimpleNamespace(store=None, bead="b", env=mock.Mock(), checkpoints=mock.Mock(), dead=None,
                               Blocked=Blocked, moved=False)
        once = RunOnce(host)
        timer = FakeDeadline()
        with timer.patched(), mock.patch("taskloop.app.run.run_once.Lease"), \
                mock.patch("taskloop.app.run.run_once.LIVENESS", LivenessCaps(run_s=0.02)), \
                mock.patch.object(once, "run", side_effect=lambda *a: timer.wait(0.5)), \
                mock.patch.object(once, "close_out") as close:
            assert once.go() == 2
        assert close.call_args.args[1].outcome.kind is Kind.OWNER_PARK
        assert "deadline" in close.call_args.args[1].outcome.detail


class LockWait(Case):
    def test_lock_wait_has_finite_timeout_and_a_transient_stop(self):
        host = FakeWaitsHost()
        waits = Waits(host)

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
