"""Owner waiting rules use injected state readers and a clock, without sleeping."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from taskloop.app.asks import owner_verbs as waiting
from tlkernel.run import RunState


@pytest.mark.parametrize(("state", "reason", "expected"), [
    (RunState.RUNNING, "", None),
    (RunState.DONE, "", (0, "ended done: run")),
    (RunState.PARKED, "hold", (11, "ended parked: run: hold")),
    (RunState.FAILED, "broken", (11, "ended failed: run: broken")),
    (RunState.LOST, "dead", (12, "lost: run: dead")),
])
def test_verdict_maps_recorded_state(monkeypatch, state, reason, expected):
    reconcile = Mock()
    monkeypatch.setattr(waiting.runlife, "reconcile", reconcile)
    locator = Mock()
    locator.get.return_value = SimpleNamespace(manifest=SimpleNamespace(state=state, reason=reason))
    monkeypatch.setattr(waiting, "RunLocator", lambda cfg: locator)
    cfg = Mock()
    assert waiting.verdict(cfg, "run", 10) == expected
    reconcile.assert_called_once_with(cfg, 10)


def test_wait_polls_to_exact_deadline(monkeypatch):
    monkeypatch.setattr(waiting, "newest_run", lambda cfg, bead: "run")
    monkeypatch.setattr(waiting, "verdict", lambda *args: None)
    asks = Mock()
    asks.live.return_value = []
    ticks = iter([10, 10, 12, 14, 15])
    sleep = Mock()
    assert waiting.wait(Mock(), asks, "repo", "bead", 5, lambda: next(ticks), sleep) == (
        14, "timeout: nothing ended or asked in 5 s")
    assert [call.args[0] for call in sleep.call_args_list] == [2, 2, 1]


def test_ended_run_takes_precedence_over_ask(monkeypatch):
    monkeypatch.setattr(waiting, "newest_run", lambda cfg, bead: "run")
    monkeypatch.setattr(waiting, "verdict", lambda *args: (0, "ended done: run"))
    asks, sleep = Mock(), Mock()
    assert waiting.wait(Mock(), asks, "repo", "bead", 0, lambda: 10, sleep) == (0, "ended done: run")
    asks.live.assert_not_called()
    sleep.assert_not_called()
