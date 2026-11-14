"""Events location has the same explicit path in both CLI output modes."""

import json
from pathlib import Path

import pytest

from taskloop import cli_composition, cli_step
from taskloop.attempt_status import AttemptView, Shown
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.cli import main
from taskloop.evidence_files import EvidenceFiles
from taskloop.machine_config import Loaded, defaults


def test_show_prints_the_owning_events_path_in_human_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    files = EvidenceFiles(tmp_path / "custom artifacts with spaces")
    key = AttemptKey("attempt", "dispatch", 1)
    directory = files.root / files.directory(key)
    view = AttemptView("tasks", "tl-1", "plan", key.attempt_id, "s1", "admitted", "none",
                       AttemptResult("pending", "admitted"), False, "start")
    shown = Shown(view, directory, directory / "entry.log", files.events_path(key))
    loaded = Loaded(tmp_path / "config.toml", False, defaults(tmp_path))
    monkeypatch.setattr(cli_composition, "load_config", lambda *_args: loaded)
    monkeypatch.setitem(cli_step.OPERATIONS, ("step", "show"), lambda *_args: shown)
    assert main(["step", "show", "tl-1", "--backlog", "tasks"]) == 0
    human = capsys.readouterr()
    assert human.err == "" and f"Events: {shown.events_path}\n" in human.out
    assert main(["step", "show", "tl-1", "--backlog", "tasks", "--json"]) == 0
    structured = capsys.readouterr()
    assert structured.err == ""
    assert json.loads(structured.out)["events_path"] == str(files.events_path(key))
    assert not files.root.exists()
