"""Land's closing adapters bind the filer and repo-specific cleanup inputs."""
from collections.abc import Callable
from pathlib import Path

import pytest
from support.facts import fake_facts
from support.memstores import fake_stores

from taskloop.app.land import cleanup
from taskloop.app.land.closing import LandCleanups, LandFollowUps
from taskloop.contracts.gitport import Git
from taskloop.contracts.paths import ConfigDir
from taskloop.stores.runlog import RunLog


def test_followups_returns_filers_list():
    leftovers = [{"title": "remaining work"}]
    calls: list[str] = []

    def file() -> list[dict[str, str]]:
        calls.append("file")
        return leftovers

    assert LandFollowUps(file).file() is leftovers
    assert calls == ["file"]


def test_cleanup_uses_repo_slot_predicate_and_base(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    _, ports = fake_facts(workdir)
    cfg = ConfigDir(workdir)
    log = RunLog(fake_stores().run_log("run"))
    lookups: list[tuple[str, str]] = []
    calls: list[tuple[Git, RunLog, Callable[[str], bool], str, ConfigDir]] = []

    def is_slot(path: str) -> bool:
        return path == "slot-1"

    def slot_check(repo: str) -> Callable[[str], bool]:
        lookups.append(("slots", repo))
        return is_slot

    def base_of(repo: str) -> str:
        lookups.append(("base", repo))
        return "origin/topic"

    def record(git: Git, log: RunLog, predicate: Callable[[str], bool], base: str, *, cfg: ConfigDir) -> None:
        calls.append((git, log, predicate, base, cfg))

    monkeypatch.setattr(cleanup, "retry_logged", record)
    LandCleanups(ports.git, log, cfg, slot_check, base_of).retry("repo-1")
    assert lookups == [("slots", "repo-1"), ("base", "repo-1")]
    assert calls == [(ports.git, log, is_slot, "origin/topic", cfg)]
