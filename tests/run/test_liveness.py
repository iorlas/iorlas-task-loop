"""Wall deadlines and bounded lock waits survive slow or hung work."""
import contextlib
import unittest
from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support.paths  # noqa: F401
from support.fake_deadline import FakeDeadline
from support.narrow_hosts import FakeWaitsHost

from taskloop.app.run.blocked import Blocked
from taskloop.app.run.run_once import RunOnce
from taskloop.app.run.waits import Waits
from taskloop.contracts import log as rec
from taskloop.contracts.kinds import Kind
from taskloop.domain.lanes.liveness import LIVENESS, LivenessCaps


class RunDeadline(unittest.TestCase):
    def test_deadline_parks_and_still_closes_a_hung_run(self):
        host = SimpleNamespace(store=None, bead="b", env=mock.Mock(), checkpoints=mock.Mock(), dead=None,
                               Blocked=Blocked, moved=False)
        once = RunOnce(host)
        timer = FakeDeadline()
        with timer.patched(), mock.patch("taskloop.app.run.run_once.Lease"), \
                mock.patch("taskloop.app.run.run_once.LIVENESS", LivenessCaps(run_s=0.02)), \
                mock.patch.object(once, "run", side_effect=lambda *a: timer.wait(0.5)), \
                mock.patch.object(once, "close_out") as close:
            self.assertEqual(once.go(), 2)
        self.assertIs(close.call_args.args[1].outcome.kind, Kind.OWNER_PARK)
        self.assertIn("deadline", close.call_args.args[1].outcome.detail)


class LockWait(unittest.TestCase):
    def test_lock_wait_has_finite_timeout_and_a_transient_stop(self):
        host = FakeWaitsHost()
        waits = Waits(host)

        @contextlib.contextmanager
        def busy(path: Path | str, holder: str, waiting: Callable[[str], None] | None = None,
                 timeout: float | None = None, check: Callable[[], None] | None = None) -> Generator[Path | str]:
            assert timeout is not None
            assert waiting is not None
            self.assertEqual(timeout, LIVENESS.lock_wait_s)
            waiting("holder")
            host.fake_clock.advance(timeout)
            raise TimeoutError("holder")
            yield path

        with mock.patch.object(host, "os_lock", busy), self.assertRaises(Blocked) as stopped, waits.locked("land_lock", "lock"):
            self.fail("acquired a busy lock")
        self.assertIs(stopped.exception.kind, Kind.PAUSE_LANE)
        rows = [row.rec for row in host.stores.run_log("run").read_from(0).items]
        self.assertEqual(sum(isinstance(row, rec.WaitEnd) for row in rows), 1)
        self.assertEqual(host.waited, LIVENESS.lock_wait_s)
