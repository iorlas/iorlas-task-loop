"""Owner waiting rules use injected state readers and a clock, without sleeping."""
from unittest.mock import Mock

import pytest

from taskloop.app.asks import owner_verbs as waiting
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.run import RunManifest, RunState
from tltestkit.narrow import must
from tltestkit.runs import manifest


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
    locator.get.return_value = Mock(manifest=RunManifest(run="run", repo="/repo", bead="b", started=0, state=state, reason=reason))
    monkeypatch.setattr(waiting, "RunLocator", lambda cfg: locator)
    cfg = Mock()
    assert waiting.verdict(cfg, "run", 10) == expected
    reconcile.assert_not_called()


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


def test_verdict_sees_dead_run_without_writing(tmp_path, monkeypatch):
    cfg = ConfigDir(tmp_path)
    before = manifest(cfg, "run", "b", state=RunState.RUNNING, host="here", pid=123, heartbeat=10).manifest
    monkeypatch.setattr(waiting.runlife, "host_name", lambda: "here")
    monkeypatch.setattr(waiting.runlife, "pid_alive", lambda *args: False)
    now = 10 + waiting.runlife.STALE_AFTER
    code, reason = must(waiting.verdict(cfg, "run", now))
    assert code == waiting.CRASHED
    assert waiting.runlife.lost_reason(before, now) in reason
    assert must(RunLocator(cfg).get("run")).manifest == before


@pytest.mark.parametrize(("age", "included"), [(0, True), (120, True), (300, False)])
def test_repo_runs_keeps_live_and_suspect_without_writing(tmp_path, monkeypatch, age, included):
    cfg = ConfigDir(tmp_path)
    before = manifest(cfg, "run", "b", state=RunState.RUNNING, host="here", pid=123, heartbeat=10).manifest
    monkeypatch.setattr(waiting.runlife, "host_name", lambda: "here")
    monkeypatch.setattr(waiting.runlife, "pid_alive", lambda *args: False)
    assert waiting.repo_runs(cfg, "/repo", 10 + age) == (["run"] if included else [])
    assert must(RunLocator(cfg).get("run")).manifest == before
    if included:
        assert waiting.verdict(cfg, "run", 10 + age) is None
