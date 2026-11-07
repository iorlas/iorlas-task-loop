"""Crash reports observe dead engines without changing authoritative run state."""

from taskloop.app.report import card
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.run import RunState
from tltestkit.narrow import must
from tltestkit.runs import manifest


def test_crashes_sees_dead_run_without_writing(tmp_path, monkeypatch):
    cfg = ConfigDir(tmp_path)
    bundle = manifest(cfg, "run", "b", started=1, state=RunState.RUNNING, host="here", pid=123, heartbeat=10)
    bundle.log.touch()
    monkeypatch.setattr(card.runlife, "host_name", lambda: "here")
    monkeypatch.setattr(card.runlife, "pid_alive", lambda *args: False)
    now = 10 + card.runlife.STALE_AFTER
    rows = card.crashes("/repo", 0, now, [], cfg, now=now)
    assert len(rows) == 1
    assert rows[0]["run"] == "run"
    assert card.runlife.lost_reason(bundle.manifest, now) in rows[0]["why"]
    assert must(RunLocator(cfg).get("run")).manifest == bundle.manifest
