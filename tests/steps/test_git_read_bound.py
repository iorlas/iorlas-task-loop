"""The machine config's `git_read_seconds` reaches every Git view and every entry's argv, and a timed-out read is
`unavailable:git` with the library's message, through one public operation (`slot adopt`)."""

from pathlib import Path

import pytest
from git_porcelain import GitTimeout, RealRepo

from taskloop import cli_composition
from taskloop.cli import main
from taskloop.cli_step import views_for
from taskloop.git_views import PUSH_TIMEOUT, GitViews
from taskloop.machine_config import Flags, Loaded
from taskloop.operations import Failed
from taskloop.slot_files import RealSlotFiles
from taskloop.slots import SlotGit


def test_the_config_value_bounds_every_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "c.toml"
    config.write_text("git_read_seconds = 45\n")
    loaded = cli_composition.load_config(str(config), Flags())
    assert isinstance(loaded, Loaded)
    views = views_for(loaded)
    for view in (views.checkouts(tmp_path), views.remotes(tmp_path), views.checkouts(tmp_path, git_dir=tmp_path / ".git")):
        assert isinstance(view, RealRepo) and view.read_timeout == 45
    pushing = views.remotes(tmp_path)
    assert isinstance(pushing, RealRepo) and pushing.remote_timeout == PUSH_TIMEOUT
    assert main(["--config", str(config), "config", "show"]) == 0


def test_views_without_a_configured_bound_keep_the_default(tmp_path: Path) -> None:
    view = GitViews().checkouts(tmp_path)
    assert isinstance(view, RealRepo) and view.read_timeout == 600


def test_a_timed_out_read_is_unavailable_git_with_the_library_message(tmp_path: Path) -> None:
    def blocked(path: Path, *, git_dir: Path | None = None) -> RealRepo:
        raise GitTimeout("git status timed out after 30s", retryable=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    result = cli_composition.adopt(tmp_path / "f.db", repo, tmp_path / "slots", 1, SlotGit(blocked, RealSlotFiles()))
    assert result == Failed("unavailable", "git", "git status timed out after 30s")
