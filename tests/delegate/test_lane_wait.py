"""Lane recovery uses fake time and keeps every leg's charges inside delegate."""

import argparse

import pytest
from any_agent.supervisor import RunHooks
from support.fake_clock import FakeClock

from delegate.app import run
from delegate.app.run_legs import CONTINUE_NOTE, lane_wait


def recover(first, following):
    clock, calls = FakeClock(), []
    legs = iter(following)

    def launch(brief, args, kind):
        calls.append((brief, args.resume, kind))
        return next(legs)

    result = lane_wait(first, launch, "original", argparse.Namespace(resume=None), clock.now, clock.advance, clock.now)
    return result, calls, clock.now() - 1_000_000


@pytest.mark.parametrize("reason", ["busy", "vendor_blip", "duplicate_task"])
@pytest.mark.parametrize("gap,expected", [(None, 20), (7, 7), (180, 180), (181, 20), (-1, 20)])
def test_polls_relaunch_at_most_three_times(reason, gap, expected):
    first = {"outcome": reason, "retry_after": gap, "cost": 2}
    result, calls, waited = recover(first, [dict(first) for _ in range(3)])
    assert result["outcome"] == reason
    assert result["cost"] == 8
    assert calls == [("original", None, "lane_poll")] * 3
    assert waited == expected * 3


@pytest.mark.parametrize("reason", ["rate_limited", "held", "hung"])
def test_predicted_within_cap_waits_and_merges_costs(reason):
    first = {"outcome": reason, "retry_after": 1_000_120, "cost": 2, "tokens": {"in": 10}}
    result, calls, waited = recover(first, [{"outcome": None, "cost": 3, "tokens": {"in": 20}}])
    assert waited == 120
    assert calls == [("original", None, "lane_wait")]
    assert result["cost"] == 5
    assert result["tokens"] == {"in": 30, "cached": 0, "out": 0}


def test_predicted_beyond_cap_returns_unchanged():
    first = {"outcome": "rate_limited", "retry_after": 1_000_181}
    result, calls, waited = recover(first, [])
    assert result is first
    assert (calls, waited) == ([], 0)


def test_predicted_cap_counts_prior_lane_waits():
    first = {"outcome": "busy", "retry_after": 100}
    result, calls, waited = recover(first, [{"outcome": "held", "retry_after": 1_000_181}])
    assert result["outcome"] == "held"
    assert calls == [("original", None, "lane_poll")]
    assert waited == 100


@pytest.mark.parametrize("resumable,ref", [(True, "session"), (False, "session"), (True, None)])
def test_only_resumable_sessions_are_resumed(resumable, ref):
    first = {"outcome": "busy", "resumable": resumable, "ref": ref}
    _, calls, _ = recover(first, [{"outcome": None}])
    expected_ref = ref if resumable else None
    assert calls == [(CONTINUE_NOTE if expected_ref else "original", expected_ref, "lane_poll")]


@pytest.mark.parametrize("reason", ["network", "logged_out", "worker_failed"])
def test_other_stops_return_without_waiting(reason):
    first = {"outcome": reason}
    result, calls, waited = recover(first, [])
    assert result is first
    assert (calls, waited) == ([], 0)


def test_launch_records_lane_attempts(monkeypatch):
    clock = FakeClock()
    legs = iter([{"outcome": "busy"}, {"outcome": "held", "retry_after": 1_000_040}, {"outcome": None}])
    monkeypatch.setattr(run.launch, "launch_worker", lambda *args: next(legs))
    worker = run.Run(argparse.Namespace(resume=None, schema=None), {}, now=clock.now, sleep=clock.advance, wall=clock.now)
    result = worker._launch({"lane": "lane", "model": "model"}, "original", "run", 0, RunHooks(), False)
    assert result["outcome"] is None
    assert [leg["kind"] for leg in worker.attempts] == ["first", "lane_poll", "lane_wait"]


def test_predicted_budget_is_shared_and_includes_the_boundary():
    first = {"outcome": "held", "retry_after": 1_000_100}
    result, calls, waited = recover(first, [
        {"outcome": "held", "retry_after": 1_000_180},
        {"outcome": "held", "retry_after": 1_000_181},
    ])
    assert (result["retry_after"], waited) == (1_000_181, 180)
    assert [call[2] for call in calls] == ["lane_wait", "lane_wait"]


def test_expired_prediction_relaunches_once_without_spinning():
    first = {"outcome": "held", "retry_after": 999_999}
    result, calls, waited = recover(first, [dict(first)])
    assert result["outcome"] == "held"
    assert (len(calls), waited) == (1, 0)


def test_prediction_uses_wall_time_with_a_distinct_monotonic_clock():
    clock, calls = FakeClock(), []

    def launch(*args):
        calls.append(args)
        return {"outcome": None}

    result = lane_wait(
        {"outcome": "held", "retry_after": 1_000_030}, launch, "original", argparse.Namespace(resume=None),
        lambda: clock.now() - 1_000_000, clock.advance, clock.now,
    )
    assert result["outcome"] is None
    assert (len(calls), clock.now()) == (1, 1_000_030)
