"""Loop catch-alls preserve crash evidence while keeping their exit and retry behavior."""
import contextlib
import sys
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.loop import loop as module
from taskloop.app.loop.loop import Loop


class FailureLogging(Case):
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

        with pytest.raises(RuntimeError) as raised:
            Loop.main(loop)

        assert raised.value is error
        loop.left.assert_called_once_with("crash", "RuntimeError: queue failed")
        text = loop.say.call_args.args[0]
        assert "Traceback (most recent call last)" in text
        assert "RuntimeError: queue failed" in text
        assert [call[0] for call in calls.mock_calls] == ["say", "fall_back"]
        loop.write_exit.assert_called_once_with()

    def test_prune_failure_logs_full_traceback_and_allows_loop_to_continue(self):
        loop = mock.Mock(spec=Loop)
        loop.env = mock.Mock()
        message = "x" * 400 + " prune failed"
        loop.env.prune.side_effect = RuntimeError(message)

        assert Loop.prune(loop) is None

        text = loop.say.call_args.args[0]
        assert "warn: prune failed" in text
        assert "Traceback (most recent call last)" in text
        assert "RuntimeError: " + message in text


def test_run_reconciles_once_at_the_start_of_every_pass(monkeypatch):
    loop = mock.Mock(spec=Loop)
    loop.env = mock.Mock()
    loop.env.now.side_effect = [10, 20, 30]
    events = []
    def reconcile(cfg, now):
        assert cfg is loop.env.cfgdir
        events.append(("reconcile", now))
        return ["dead"] if now == 20 else []
    def step():
        events.append(("step", None))
        return 7 if len(events) >= 6 else None
    monkeypatch.setattr(module.runlife, "reconcile", reconcile)
    loop.step.side_effect = step
    assert Loop.run(loop) == 7
    assert events == [("reconcile", 10), ("step", None), ("reconcile", 20), ("step", None),
                      ("reconcile", 30), ("step", None)]
    loop.say.assert_called_once_with("run dead is lost: its process is gone and it recorded no end")
