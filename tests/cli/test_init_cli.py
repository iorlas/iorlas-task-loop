"""`tl init` writes whichever of the profile and the workflow file is absent into a temporary working tree, never over one."""

import json
from pathlib import Path

import pytest

from taskloop.cli import main
from taskloop.init_files import PROFILE_STARTER
from taskloop.profile import Profile, parse
from taskloop.workflow_starter import STARTER


def test_init_writes_both_files_once_and_leaves_them_to_the_person_to_commit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile, workflow = tmp_path / ".task-loop.json", tmp_path / ".task-loop" / "workflows" / "mine.toml"
    assert main(["init", "--checkout", str(tmp_path), "--workflow", "mine"]) == 0
    out = capsys.readouterr().out
    assert profile.read_text() == PROFILE_STARTER and workflow.read_text() == STARTER
    assert f"Wrote {profile}" in out and f"Wrote {workflow}" in out and "uncommitted" in out


def test_init_keeps_a_file_that_exists_and_writes_only_the_other(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile = tmp_path / ".task-loop.json"
    profile.write_text("mine")
    assert main(["init", "--checkout", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    created = [str(tmp_path / ".task-loop/workflows/default.toml")]
    assert profile.read_text() == "mine" and data["kept"] == [str(profile)] and data["created"] == created
    assert main(["init", "--checkout", str(tmp_path)]) == 0
    assert "uncommitted" not in capsys.readouterr().out and profile.read_text() == "mine"


def test_the_starter_profile_loads_and_requires_no_check_so_admission_refuses_it() -> None:
    profile = parse(PROFILE_STARTER.encode())
    assert isinstance(profile, Profile) and profile.setup and not profile.checks and not profile.required


def test_an_unusable_checkout_or_name_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "--checkout", str(tmp_path / "absent")]) == 1
    assert "cannot be written" in capsys.readouterr().err and not (tmp_path / "absent").exists()
    with pytest.raises(SystemExit) as result:
        main(["init", "--workflow", "../x"])
    assert result.value.code == 2


def test_init_reports_created_kept_and_failed_separately(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".task-loop").write_text("a file, not a folder")
    assert main(["init", "--checkout", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    profile, workflow = tmp_path / ".task-loop.json", tmp_path / ".task-loop" / "workflows" / "default.toml"
    assert f"Wrote {profile}" in out and f"Failed {workflow}: Not a directory" in out and "Kept" not in out


def test_init_json_lists_failures_with_their_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".task-loop").write_text("x")
    assert main(["init", "--checkout", str(tmp_path), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["created"] == [str(tmp_path / ".task-loop.json")] and data["kept"] == []
    assert [item["path"] for item in data["failed"]] == [str(tmp_path / ".task-loop/workflows/default.toml")]


def test_init_fails_when_a_file_stands_where_the_workflow_folder_must_be(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".task-loop").mkdir()
    (tmp_path / ".task-loop" / "workflows").write_text("x")
    assert main(["init", "--checkout", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "a file is in the way of its folder" in out and "Kept" not in out
