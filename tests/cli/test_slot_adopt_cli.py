"""`tl slot adopt`: the checkout, slots root and count come from flags, the config and the defaults."""

import json
from pathlib import Path

import pytest

from taskloop import cli_composition
from taskloop.cli import main
from taskloop.operations import Adoption
from taskloop.slots import Adopted, NotAdopted, SlotGit


def test_adopt_takes_its_paths_and_count_from_flags_config_and_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[Path, Path, Path, int]] = []

    def adopt(database: Path, checkout: Path, root: Path, count: int, _git: SlotGit) -> Adoption:
        calls.append((database, checkout, root, count))
        return Adoption((Adopted("s1", root / "id" / "s1"), NotAdopted("s2", "not_listed", root / "id" / "s2")))

    monkeypatch.setattr(cli_composition, "adopt", adopt)
    config = tmp_path / "scratch.toml"
    config.write_text("slot_count = 2\n")
    assert main(["--config", str(config), "slot", "adopt", str(tmp_path / "repo"), "--slots-root", str(tmp_path / "slots"), "--json"]) == 1
    assert calls == [(tmp_path / "home" / ".local/state/task-loop/factory.db", tmp_path / "repo", tmp_path / "slots", 2)]
    assert json.loads(capsys.readouterr().out) == {
        "slots": [
            {"name": "s1", "adopted": True, "reason": None, "path": str(tmp_path / "slots/id/s1")},
            {"name": "s2", "adopted": False, "reason": "not_listed", "path": str(tmp_path / "slots/id/s2")},
        ]
    }
