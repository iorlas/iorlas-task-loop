"""Loop catch-alls preserve crash evidence while keeping their exit and retry behavior."""
import contextlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.loop.loop import Loop


class FailureLogging(unittest.TestCase):
    def test_crash_logs_traceback_before_fallback_and_records_exit_detail(self):
        loop = mock.Mock(spec=Loop)
        loop.exit = {}
        loop.dropped = ""
        loop.files = mock.Mock()
        loop.files.lock = contextlib.nullcontext
        loop.env = mock.Mock()
        error = RuntimeError("queue failed")
        loop.run.side_effect = error
        calls = mock.Mock()
        calls.attach_mock(loop.say, "say")
        calls.attach_mock(loop.fall_back, "fall_back")

        with self.assertRaises(RuntimeError) as raised:
            Loop.main(loop)

        self.assertIs(raised.exception, error)
        loop.left.assert_called_once_with("crash", "RuntimeError: queue failed")
        text = loop.say.call_args.args[0]
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("RuntimeError: queue failed", text)
        self.assertEqual([call[0] for call in calls.mock_calls], ["say", "fall_back"])
        loop.write_exit.assert_called_once_with()

    def test_prune_failure_logs_full_traceback_and_allows_loop_to_continue(self):
        loop = mock.Mock(spec=Loop)
        loop.env = mock.Mock()
        message = "x" * 400 + " prune failed"
        loop.env.prune.side_effect = RuntimeError(message)

        self.assertIsNone(Loop.prune(loop))

        text = loop.say.call_args.args[0]
        self.assertIn("warn: prune failed", text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("RuntimeError: " + message, text)
