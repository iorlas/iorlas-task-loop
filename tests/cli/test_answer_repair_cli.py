"""The CLI start consumer uses the shared answer repair before terminal reporting."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRemote, FakeRepo
from round_bench import Factory, Tracker, scripts, task
from sqlite_store import Store
from test_attempt import PLAN, fake

from taskloop import cli_composition
from taskloop.cli import main
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.operations import Failed, StartPorts


@pytest.mark.parametrize("valid", [False, True], ids=["invalid-repair", "valid-repair"])
def test_cli_repairs_once_and_reports_the_latest_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], valid: bool,
) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "one", ".task-loop.json": "{}"})
    repo = FakeRepo.clone(remote, tmp_path / "main")
    slot = repo.add_worktree(tmp_path / "slots" / "s1", "HEAD")
    store = Store(SCHEMA)
    con = store.open_rw(tmp_path / "factory.db")
    assert con is not None
    factory = Factory(con, tmp_path, slot, PinnedViews(repo), FakeSlotFiles(repo), Tracker(task("tl-1")))

    @contextmanager
    def opener(_database: Path, _artifacts: Path, _views: GitViews) -> Generator[StartPorts | Failed]:
        yield factory.starting()

    monkeypatch.setattr(cli_composition, "open_start", opener)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    arguments = ["step", "start", "tl-1", "--backlog", "tasks", "--tracker-root", "/tracker", "--checkout", str(repo.path),
                 "--model", "m", "--effort", "high", "--minutes", "30", "--json"]
    first = fake("not json", refs=("saved",))
    factory.agents["tl-1", "plan"] = first
    try:
        assert main(arguments) == 0
        original = json.loads(capsys.readouterr().out)["attempt_id"]
        correction = fake(json.dumps({**PLAN, "paths": ["wrong.md"]}), refs=("saved",))
        factory.agents["tl-1", "plan"] = correction
        if valid:
            scripts(factory, slot, "tl-1")
        assert main(arguments) == 0
        repaired = json.loads(capsys.readouterr().out)["attempt_id"]
        assert repaired != original and len(factory.ran) == 2 and not factory.tracker.comments
        if not valid:
            assert main(arguments) != 0
            output = capsys.readouterr()
            assert "paths_location:" in output.out + output.err and "json:" not in output.out + output.err
            assert len(first.calls) == len(correction.calls) == 1 and len(factory.ran) == 2
        else:
            assert factory.next_words()["tl-1"] == ("plan", "verify")
    finally:
        con.close()
