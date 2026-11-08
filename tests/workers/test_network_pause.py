"""A worker network stop ends the engine call without probing, waiting, or resuming."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from taskloop.app.workers import account_acts
from taskloop.domain.accounts import policy as lp
from tlkernel.delegate import DelegateResult


def test_network_stop_pauses_immediately(monkeypatch):
    blocked = RuntimeError("PAUSE_NETWORK")
    ops = Mock()
    ops.blocked.return_value = blocked
    worker = Mock(ops=ops)
    host = SimpleNamespace(
        clock=SimpleNamespace(now=lambda: 100), log=Mock(), steps=Mock(),
        cfg=None, bead="bead", plan_data=None, budget=SimpleNamespace(labels=[]),
        delegation=Mock(), halt_point=Mock(), waits=Mock(),
    )
    call = SimpleNamespace(
        counts={"attempt": 0},
        thread="writer", denied_retried=False, secret_fp=False, node="write", step="write",
        limit_s=100, role="worker",
    )
    monkeypatch.setattr(account_acts.writer_pin, "prefer", lambda *args: "")
    acts = account_acts.AccountActs(host, worker)
    stop = lp.Stop("machine", "transient", "poll", reason="network")
    result = DelegateResult()
    with pytest.raises(RuntimeError, match="PAUSE_NETWORK"):
        acts.act(call, result, stop, lp.decide(stop, acts.ctx_of(call)))
    assert ops.blocked.call_args.args[1] == "PAUSE_NETWORK"
    assert host.retry_after == 0
    host.delegation.net_probe.assert_not_called()
    host.halt_point.assert_not_called()
    host.waits.start.assert_not_called()
    worker.again.assert_not_called()
