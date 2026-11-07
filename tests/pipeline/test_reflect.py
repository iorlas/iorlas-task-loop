"""Reflection is optional and never dispatches when its safety checks refuse it."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from support.pipeline_ports import FakeTrustRefusal

from taskloop.app.pipeline.reflect import Reflector
from tlkernel import childenv


def host():
    return Mock(cfg=SimpleNamespace(reflect=True, base="origin/main"), dry=False, route="route", stop_pending=False,
                sessions=[{"node": "write"}], wt="tree", bead="t-1")


def test_trust_refusal_warns_without_building_a_prompt():
    run = host()
    refusal = FakeTrustRefusal("unapproved roots")
    reflector = Reflector(run, refusal, childenv.delegate_call_env)
    reflector.reflect_prompt = Mock(side_effect=AssertionError("must not build prompt"))
    assert reflector.reflect_run("done", "finished") is None
    run.warn.assert_called_once_with("no reflection: unapproved roots")
    reflector.reflect_prompt.assert_not_called()
    assert refusal.calls == [(run.git, run.wt, run.cfg.base, run.store.show.return_value)]
    run.delegation.route.assert_not_called()


@pytest.mark.parametrize("dry,nodes,why", [(True, ["write"], ""), (False, [], ""),
                                          (False, ["plan", "look"], ""), (False, ["write"], "paused: owner")])
def test_unworthy_runs_are_skipped(dry, nodes, why):
    run = host()
    run.dry, run.sessions = dry, [{"node": node} for node in nodes]
    assert not Reflector(run, FakeTrustRefusal(), childenv.delegate_call_env).worth_asking(why)


@pytest.mark.parametrize("node", ["write", "review", "verify"])
def test_worker_sessions_are_worth_reflecting_on(node):
    run = host()
    run.sessions = [{"node": node}]
    assert Reflector(run, FakeTrustRefusal(), childenv.delegate_call_env).worth_asking("finished")


def test_over_cap_prompt_skips_dispatch():
    run = host()
    reflector = Reflector(run, FakeTrustRefusal(), childenv.delegate_call_env)
    reflector.reflect_prompt = Mock(return_value="x" * 1_000_000)
    assert reflector.reflect_run("done", "finished") is None
    assert "no reflection:" in run.warn.call_args.args[0]
    run.delegation.route.assert_not_called()
