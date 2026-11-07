"""Worker network recovery stays inside delegate, using only fake time and launches."""

import argparse

import pytest
from any_agent.supervisor import RunHooks

from delegate.app import net, run
from delegate.app.run_legs import CONTINUE_NOTE
from tltestkit.fake_clock import FakeClock


@pytest.mark.parametrize("started,ref", [(True, "session-1"), (False, None), (False, "unstarted-session")])
def test_network_returns_and_relaunches_with_merged_usage(monkeypatch, started, ref):
    clock, probes, calls = FakeClock(), iter([False, False, True]), []
    monkeypatch.setattr(net, "net_up", lambda lane: next(probes))
    first = {"outcome": "network", "started": started, "ref": ref, "cost": 2,
             "tokens": {"in": 10, "out": 3}, "denied": [{"kind": "first"}]}
    last = {"outcome": None, "ref": ref, "cost": 3,
            "tokens": {"in": 20, "out": 4}, "denied": [{"kind": "last"}]}
    legs = iter([first, last])

    def launch(d, brief, args, *rest):
        calls.append((brief, args.resume))
        return next(legs)

    monkeypatch.setattr(run.launch, "launch_worker", launch)
    args = argparse.Namespace(resume=None, schema=None)
    worker = run.Run(args, {}, brief="original", now=clock.now, sleep=clock.advance)
    result = worker._launch({"lane": "lane", "model": "model"}, "original", "run", 0, RunHooks(), False)
    assert calls == [("original", None), (CONTINUE_NOTE if started else "original", ref if started else None)]
    assert clock.now() - 1_000_000 == 35
    assert result["outcome"] is None
    assert (result["cost"], result["tokens"]) == (5, {"in": 30, "cached": 0, "out": 7})
    assert result["denied"] == [{"kind": "first"}, {"kind": "last"}]
    assert [leg["kind"] for leg in worker.attempts] == ["first", "network_rerun"]


def test_network_never_returns_waits_exactly_cap_and_keeps_stop(monkeypatch):
    clock, sleeps, launches = FakeClock(), [], []
    monkeypatch.setattr(net, "net_up", lambda lane: False)
    stopped = {"outcome": "network", "ref": "session", "started": True, "cost": 2,
               "stop": {"scope": "machine", "permanence": "transient", "retry": {"kind": "poll"}}}

    def sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)

    def launch(*args):
        launches.append(args)
        return stopped.copy()

    monkeypatch.setattr(run.launch, "launch_worker", launch)
    worker = run.Run(argparse.Namespace(resume=None, schema=None), {}, now=clock.now, sleep=sleep)
    result = worker._launch({"lane": "lane", "model": "model"}, "original", "run", 0, RunHooks(), False)
    assert sum(sleeps) == clock.now() - 1_000_000 == 600
    assert sleeps == [5, 10, 20, 40, 60, 120, 120, 120, 105]
    assert len(launches) == 1
    assert result == {key: value for key, value in stopped.items() if key != "started"}


def test_a_failed_canary_is_the_answer_and_is_not_waited_on(monkeypatch):
    clock, legs = FakeClock(), []
    monkeypatch.setattr(net, "net_up", lambda lane: True)

    def launch(d, brief, args, *rest):
        legs.append(brief)
        return {"outcome": "network", "started": True, "ref": "canary-session"}

    monkeypatch.setattr(run.launch, "launch_worker", launch)
    worker = run.Run(argparse.Namespace(resume=None, schema=None), {}, now=clock.now, sleep=clock.advance)
    result = worker._launch({"lane": "lane", "model": "model"}, "original", "run", 0, RunHooks(), True)
    assert len(legs) == 1  # the canary only: the real brief is never sent
    assert result["outcome"] == "network"
    assert clock.now() - 1_000_000 == 0
