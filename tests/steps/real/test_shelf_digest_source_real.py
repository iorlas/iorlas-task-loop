"""Hermetic object reads stay pinned across checkout edits and ref movement."""

from pathlib import Path

import pytest
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git

from taskloop.git_views import GitViews
from taskloop.shelf_digest.source import CommittedSource, ReadFailure, ReadFailureReason, open_source


def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    repo = tmp_path.resolve() / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo


def test_open_source_keeps_commit_identity_before_lazy_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = started(tmp_path, monkeypatch)
    files = {"pyproject.toml": b'[project]\nname = "task-loop"\nversion = "0.1.0"',
             "uv.lock": b'[[package]]\nname = "example"\nversion = "1.0.0"',
             "packages/example/pyproject.toml": b'[project]\nname = "example"\nversion = "1.0.0"'}
    for path, data in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "original")
    views = GitViews(30).checkouts(repo)
    source = open_source(views, "main")
    assert isinstance(source, CommittedSource)
    original = source.commit
    for path in files:
        (repo / path).write_text("later committed content")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "move main")
    (repo / "uv.lock").write_text("uncommitted checkout edit")
    current = open_source(views, "main")
    assert isinstance(current, CommittedSource) and current.commit != original
    assert source.commit == original
    entries = source.entries()
    assert not isinstance(entries, ReadFailure)
    assert tuple(item.path for item in entries) == tuple(sorted(files))
    for path, data in files.items():
        assert source.read(path) == data
    assert current.read("uv.lock") == b"later committed content"


def test_real_modes_missing_paths_and_missing_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = started(tmp_path, monkeypatch)
    (repo / "regular").write_text("regular")
    (repo / "executable").write_text("executable")
    (repo / "executable").chmod(0o755)
    (repo / "link").symlink_to("regular")
    git(repo, "add", ".")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},submodule")
    git(repo, "commit", "-q", "-m", "modes")
    views = GitViews(30).checkouts(repo)
    source = open_source(views, "HEAD")
    assert isinstance(source, CommittedSource)
    assert source.read("regular") == b"regular"
    assert source.read("executable") == b"executable"
    entries = source.entries()
    assert not isinstance(entries, ReadFailure)
    assert {item.path: item.mode for item in entries} == {
        "regular": "100644", "executable": "100755", "link": "120000", "submodule": "160000",
    }
    for path, mode in [("link", "120000"), ("submodule", "160000")]:
        result = source.read(path)
        assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NOT_A_FILE
        assert path in result.explanation and mode in result.explanation
    result = source.read("absent")
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NO_PATH
    result = open_source(views, "f" * 40)
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.NO_COMMIT


def test_repository_failure_is_distinct_from_missing_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    result = open_source(GitViews(30).checkouts(tmp_path.resolve()), "HEAD")
    assert isinstance(result, ReadFailure) and result.reason == ReadFailureReason.UNAVAILABLE
    assert result.explanation
