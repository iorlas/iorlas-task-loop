"""Lifecycle exit paths settle exactly once, independently of the run body."""
import contextlib
from types import SimpleNamespace
from unittest import mock

from support.lifecycle import lifecycle

from taskloop.adapters.deadline import DeadlineExpired
from tlkernel import fence
from tlkernel.kinds import Kind
from tlkernel.run import RunState
from tlpipeline.lifecycle import Ended


def host():
    records = mock.Mock()
    records.finish.side_effect = lambda done: done
    return SimpleNamespace(checkpoints=SimpleNamespace(read=lambda: None), dead=None, prev_ck="", moved=False,
                           cfg=SimpleNamespace(run_deadline_min=1), fenced="", records=records,
                           landed_sha="", stop_deferred=contextlib.nullcontext, warn=mock.Mock(),
                           log=mock.Mock(), home=mock.Mock(), run_id="run", closer=mock.Mock(), steps=mock.Mock())


def test_fenced_body_stops_the_run_with_engine_fault():
    h = host()
    run = lifecycle(h)
    end = Ended()
    with mock.patch.object(run, "body", side_effect=fence.Fenced("taken again")), \
            mock.patch.object(run, "settle", wraps=run.settle) as settle:
        assert run.go() == 2
        end = settle.call_args.args[0]
    assert end.outcome.kind is Kind.FAULT_ENGINE
    assert end.outcome.detail == "taken again"
    h.records.settle.assert_called_once_with(RunState.STOPPED, "fenced out: taken again")


def test_deadline_parks_and_closes():
    h = host()
    run = lifecycle(h)
    with mock.patch.object(run, "body", side_effect=DeadlineExpired("run")), mock.patch.object(run, "close_out") as close:
        assert run.go() == 2
    assert close.call_args.args[1].outcome.kind is Kind.OWNER_PARK


def test_failing_close_still_settles():
    h = host()
    run = lifecycle(h)
    end = Ended()
    with mock.patch.object(run, "close", side_effect=OSError("disk")), \
            mock.patch("tlpipeline.lifecycle.RunLocator") as locator:
        locator.return_value.get.return_value = None
        run.close_out(mock.Mock(), end)
    assert end.outcome.kind is Kind.ENGINE_CRASH
    h.closer.pause.assert_called_once_with(end.outcome)
    h.records.settle.assert_called_once_with(RunState.PARKED, end.outcome.detail)


def test_moved_run_stops_lease_without_settling():
    h = host()
    h.moved = True
    lease = mock.Mock()
    lifecycle(h).close_out(lease, Ended())
    lease.stop.assert_called_once_with()
    h.records.settle.assert_not_called()
