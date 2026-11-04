"""Nested wall limits cannot cancel or extend the run's enclosing deadline."""
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import stream_proc
import support.paths  # noqa: F401
from support.fake_deadline import FakeDeadline

from taskloop.adapters import procs
from taskloop.adapters.deadline import DeadlineExpired, deadline, remaining
from taskloop.adapters.runner import StreamRunner
from taskloop.adapters.spawner import Started


class Deadlines(unittest.TestCase):
    def setUp(self):
        self.timer = FakeDeadline()
        self.enterContext(self.timer.patched())

    def test_earlier_outer_deadline_wins_and_scope_is_restored(self):
        with self.assertRaises(DeadlineExpired) as expired, deadline(0.02, "run"), deadline(0.5, "judge"):
            self.timer.wait(0.5)
        self.assertEqual(expired.exception.scope, "run")
        self.assertIsNone(remaining(None))

    def test_inner_deadline_restores_outer_timer_after_elapsed_time(self):
        with deadline(0.5, "run"):
            before = remaining(0.5)
            with self.assertRaises(DeadlineExpired), deadline(0.02, "judge"):
                self.timer.wait(0.5)
            after = remaining(0.5)
            self.assertGreater(after, 0)
            self.assertLess(after, before)

    def test_normal_return_clears_deadline(self):
        with deadline(0.02, "run"):
            pass
        self.assertIsNone(remaining(None))

    def test_hung_child_gets_the_remaining_timeout_through_stream_proc(self):
        def child(*args, timeout: float | None = None, **kwargs):
            assert timeout is not None
            self.assertAlmostEqual(timeout, 0.02)
            self.timer.clock.advance(timeout)
            return stream_proc.Result(None, None, "wall", 0, 0, None, timeout)

        with mock.patch.object(stream_proc, "run", child), self.assertRaises(DeadlineExpired), deadline(0.02, "judge"):
            procs.stream(["judge"], cwd=None, env={}, on_output=lambda _: None, timeout_s=60,
                         stop=threading.Event(), grace=0)

    def test_check_thread_inherits_the_process_deadline(self):
        with deadline(0.02, "run"), ThreadPoolExecutor(max_workers=1) as pool:
            self.assertAlmostEqual(pool.submit(remaining, 60).result(timeout=1), 0.02)

    def test_hung_delegate_uses_stream_proc_timeout_and_propagates_the_deadline(self):
        def child(*args, timeout: float | None = None, **kwargs):
            assert timeout is not None
            self.assertAlmostEqual(timeout, 0.02)
            self.timer.clock.advance(timeout)
            return stream_proc.Result(None, None, "wall", 0, 0, None, timeout)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(stream_proc, "run", child), \
                self.assertRaises(DeadlineExpired) as expired, deadline(0.02, "land judge"):
            StreamRunner(Path(tmp) / "stderr", wall=60)(["judge"])
        self.assertEqual(expired.exception.scope, "land judge")

    def test_started_child_wait_is_bounded_and_stops_its_tree_on_deadline(self):
        def hung(timeout: float | None = None):
            assert timeout is not None
            self.assertAlmostEqual(timeout, 0.02)
            self.timer.clock.advance(timeout)
            raise subprocess.TimeoutExpired(["child"], timeout)

        child = mock.Mock()
        child.wait.side_effect = hung
        with mock.patch.object(procs, "stop_tree") as stopped, self.assertRaises(DeadlineExpired), deadline(0.02, "run"):
            Started(child).wait()
        stopped.assert_called_once_with(child, grace=procs.STOP_GRACE_S)

    def test_already_expired_deadline_stops_an_owned_child_before_waiting(self):
        child = mock.Mock()
        with mock.patch.object(procs, "stop_tree") as stopped, self.assertRaises(DeadlineExpired), deadline(0.02, "run"):
            self.timer.clock.advance(0.03)
            Started(child).wait()
        child.wait.assert_not_called()
        stopped.assert_called_once_with(child, grace=procs.STOP_GRACE_S)
