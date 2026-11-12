"""The machine config's `git_read_seconds` reaches every Git view, and a timed-out read is `unavailable:git` with the
library's message, through one public operation (`slot adopt`)."""

from pathlib import Path

import pytest
from git_porcelain import GitTimeout, RealRepo

from taskloop import cli_composition, git_views
from taskloop.cli import main
from taskloop.operations import Failed
from taskloop.slot_files import RealSlotFiles
from taskloop.slots import SlotGit


@pytest.fixture(autouse=True)
def fresh_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_views, "READS", git_views.ReadBound())


def test_the_command_line_sets_the_bound_from_the_config_and_every_view_carries_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "c.toml"
    config.write_text("git_read_seconds = 45\n")
    assert main(["--config", str(config), "config", "show"]) == 0
    for view in (git_views.checkouts(tmp_path), git_views.remotes(tmp_path), git_views.checkouts(tmp_path, git_dir=tmp_path / ".git")):
        assert isinstance(view, RealRepo) and view.read_timeout == 45
    pushing = git_views.remotes(tmp_path)
    assert isinstance(pushing, RealRepo) and pushing.remote_timeout == git_views.PUSH_TIMEOUT


def test_a_view_without_a_set_bound_keeps_the_default(tmp_path: Path) -> None:
    view = git_views.checkouts(tmp_path)
    assert isinstance(view, RealRepo) and view.read_timeout == 600


def test_a_timed_out_read_is_unavailable_git_with_the_library_message(tmp_path: Path) -> None:
    def blocked(path: Path, *, git_dir: Path | None = None) -> RealRepo:
        raise GitTimeout("git status timed out after 30s", retryable=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    result = cli_composition.adopt(tmp_path / "f.db", repo, tmp_path / "slots", 1, SlotGit(blocked, RealSlotFiles()))
    assert result == Failed("unavailable", "git", "git status timed out after 30s")
