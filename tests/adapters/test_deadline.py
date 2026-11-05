"""Nested wall limits cannot cancel or extend the run's enclosing deadline."""
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest
import stream_proc
import support.paths  # noqa: F401
from support.case import Case
from support.fake_deadline import FakeDeadline

from taskloop.adapters import procs, runner
from taskloop.adapters.deadline import DeadlineExpired, deadline, remaining
from taskloop.adapters.spawner import Started


class Deadlines(Case):
    def setup_method(self):
        self.timer = FakeDeadline()
        self.enterContext(self.timer.patched())

    def test_earlier_outer_deadline_wins_and_scope_is_restored(self):
        with pytest.raises(DeadlineExpired) as expired, deadline(0.02, "run"), deadline(0.5, "judge"):
            self.timer.wait(0.5)
        assert expired.value.scope == "run"
        assert remaining(None) is None

    def test_inner_deadline_restores_outer_timer_after_elapsed_time(self):
        with deadline(0.5, "run"):
            before = remaining(0.5)
            with pytest.raises(DeadlineExpired), deadline(0.02, "judge"):
                self.timer.wait(0.5)
            after = remaining(0.5)
            assert after > 0
            assert after < before

    def test_normal_return_clears_deadline(self):
        with deadline(0.02, "run"):
            pass
        assert remaining(None) is None

    def test_hung_child_gets_the_remaining_timeout_through_stream_proc(self):
        def child(*args, timeout: float | None = None, **kwargs):
            assert timeout is not None
            assert timeout == pytest.approx(0.02, abs=5e-08)
            self.timer.clock.advance(timeout)
            return stream_proc.Result(None, None, "wall", 0, 0, None, timeout)

        with mock.patch.object(stream_proc, "run", child), pytest.raises(DeadlineExpired), deadline(0.02, "judge"):
            procs.stream(["judge"], cwd=None, env={}, on_output=lambda _: None, timeout_s=60,
                         stop=threading.Event(), grace=0)

    def test_check_thread_inherits_the_process_deadline(self):
        with deadline(0.02, "run"), ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(remaining, 60).result(timeout=1) == pytest.approx(0.02, abs=5e-08)

    def test_hung_delegate_is_cancelled_at_the_deadline_and_propagates_it(self):
        release = threading.Event()
        cancelled: list[object] = []

        def hung(request, started=None):
            assert started is not None
            started(runner.api.Handle(run_id="r", pid=1, pgid=1, start=None))
            release.wait(10)
            return {}

        def cancel(handle):
            cancelled.append(handle)
            self.timer.clock.advance(1)
            release.set()
            return mock.Mock(survivors=[])

        request = runner.api.RunRequest(role="worker", brief_file="b.md", cwd=".")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner.api, "run", hung), \
                mock.patch.object(runner.api, "cancel", cancel), mock.patch.object(runner, "POLL_S", 0.01), \
                pytest.raises(DeadlineExpired) as expired, deadline(0.02, "land judge"):
            runner.ApiRunner(Path(tmp) / "stderr", wall=60)(["judge"], request=request)
        assert expired.value.scope == "land judge"
        assert len(cancelled) == 1

    def test_started_child_wait_is_bounded_and_stops_its_tree_on_deadline(self):
        def hung(timeout: float | None = None):
            assert timeout is not None
            assert timeout == pytest.approx(0.02, abs=5e-08)
            self.timer.clock.advance(timeout)
            raise subprocess.TimeoutExpired(["child"], timeout)

        child = mock.Mock()
        child.wait.side_effect = hung
        with mock.patch.object(procs, "stop_tree") as stopped, pytest.raises(DeadlineExpired), deadline(0.02, "run"):
            Started(child).wait()
        stopped.assert_called_once_with(child, grace=procs.STOP_GRACE_S)

    def test_already_expired_deadline_stops_an_owned_child_before_waiting(self):
        child = mock.Mock()
        with mock.patch.object(procs, "stop_tree") as stopped, pytest.raises(DeadlineExpired), deadline(0.02, "run"):
            self.timer.clock.advance(0.03)
            Started(child).wait()
        child.wait.assert_not_called()
        stopped.assert_called_once_with(child, grace=procs.STOP_GRACE_S)
