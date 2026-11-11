"""Consume the shared semantic Git fake to inspect explicit checkout selections."""

from pathlib import Path

import pytest
from git_porcelain import GitReadFailure, NotARepo, RepoIdentity, WorktreeInfo
from git_porcelain.testing import FakeRemote, FakeRepo

from taskloop.repo import RepoId, UnsupportedCheckout, inspect_repo


def test_linked_checkouts_share_identity_but_keep_selection(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"a": "one"})
    repo = FakeRepo.clone(remote, tmp_path / "main")
    linked_path = tmp_path / "linked"
    linked = repo.add_worktree(linked_path, "HEAD")
    main = inspect_repo(repo, repo.path)
    other = inspect_repo(linked.repo, linked_path)
    assert main.repo_id == other.repo_id == RepoId(repo.identity().key)
    assert main.common_dir == other.common_dir
    assert other.checkout_path == linked_path
    assert other.checkout_path != repo.identity().root
    assert main.checkout_path == repo.path
    assert other.origin_url == remote.url


def test_clones_differ_and_origin_is_only_metadata(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    first = FakeRepo.clone(remote, tmp_path / "first")
    second = FakeRepo.clone(remote, tmp_path / "second")
    before = inspect_repo(first, first.path)
    assert before.repo_id != inspect_repo(second, second.path).repo_id
    first.set_remote_url("origin", "https://example.invalid/changed.git")
    after = inspect_repo(first, first.path)
    assert before.repo_id == after.repo_id
    assert before.common_dir == after.common_dir
    assert after.origin_url == "https://example.invalid/changed.git"
    local = FakeRepo.init(tmp_path / "local")
    assert inspect_repo(local, local.path).origin_url is None


@pytest.mark.parametrize("suffix", ["subdir", "file.py", "../unknown"])
def test_only_explicit_checkout_roots_are_supported(tmp_path: Path, suffix: str) -> None:
    repo = FakeRepo.init(tmp_path / "repo")
    with pytest.raises(UnsupportedCheckout, match="explicit checkout root"):
        inspect_repo(repo, repo.path / suffix)


def test_bare_record_is_explicitly_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepo.init(tmp_path / "bare")

    def bare_worktrees(*, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        return (WorktreeInfo(repo.path, None, None, True, None),)

    monkeypatch.setattr(repo, "worktrees", bare_worktrees)
    with pytest.raises(UnsupportedCheckout, match="No usable working checkout"):
        inspect_repo(repo, repo.path)


@pytest.mark.parametrize("operation", ["identity", "worktrees"])
def test_observation_failure_is_never_empty_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    repo = FakeRepo.init(tmp_path / "repo")

    def fail() -> None:
        raise GitReadFailure("cannot observe repository")

    monkeypatch.setattr(repo, operation, fail)
    with pytest.raises(GitReadFailure, match="cannot observe"):
        inspect_repo(repo, repo.path)


def test_unavailable_checkout_is_refused(tmp_path: Path) -> None:
    repo = FakeRepo.init(tmp_path / "repo")
    repo.drop_checkout(repo.path)
    with pytest.raises(NotARepo):
        inspect_repo(repo, repo.path)


def test_each_observation_is_used_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepo.init(tmp_path / "repo")
    identity, worktrees = repo.identity, repo.worktrees
    observed: list[str] = []

    def identity_once() -> RepoIdentity:
        observed.append("identity")
        return identity()

    def worktrees_once(*, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        observed.append("worktrees")
        assert with_dirty is False
        return worktrees()

    monkeypatch.setattr(repo, "identity", identity_once)
    monkeypatch.setattr(repo, "worktrees", worktrees_once)
    result = inspect_repo(repo, repo.path)
    assert result.common_dir == repo.path / ".git"
    assert observed == ["identity", "worktrees"]
