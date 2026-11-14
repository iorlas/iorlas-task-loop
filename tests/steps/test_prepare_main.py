"""Slot eligibility depends on the selected task history or origin main, independently of merging them."""

from pathlib import Path

import pytest
from git_porcelain import GitUnavailable
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from test_prepare import BRANCH, head, leave, pushed

from taskloop.prepare import Branch, branch_refusal


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "old main\n"})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.mark.parametrize("refs", ["local", "remote", "both"])
def test_new_main_slot_can_continue_the_published_task_tip(
    repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree, tmp_path: Path, refs: str,
) -> None:
    tip = leave(repo, tmp_path, BRANCH, extra=True) if refs == "local" else pushed(repo, tmp_path)
    if refs == "both":
        leave(repo, tmp_path, BRANCH, start=tip)
    target = remote.advance("main", {"other": "landed task\n"})
    assert repo.fetch().ok
    slot.park(target)
    found = branch_refusal(repo, "tl-1", (target,))
    assert isinstance(found, Branch) and found.start == tip and found.passing == (target,)
    assert head(repo, slot.path) == target and slot.branch() is None  # admission writes no Git


def test_selected_local_tip_allows_a_task_only_base_despite_a_stale_remote_tip(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path,
) -> None:
    old = pushed(repo, tmp_path)
    tip = leave(repo, tmp_path, BRANCH, start=old, extra=True)
    main = remote.advance("main", {"other": "new main\n"})
    assert repo.fetch().ok
    invalid = leave(repo, tmp_path, "other", extra=True)
    found = branch_refusal(repo, "tl-1", (invalid, tip, main))
    assert isinstance(found, Branch) and found.passing == (tip, main) and found.start == tip
    assert branch_refusal(repo, "tl-1", (invalid,)) == "branch_diverged"


def test_origin_main_commits_are_not_foreign_unpublished_work_when_local_main_lags(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path,
) -> None:
    main = remote.advance("main", {"other": "new main\n"})
    assert repo.fetch().ok
    tip = leave(repo, tmp_path, BRANCH, start=main, extra=True)
    found = branch_refusal(repo, "tl-1", (main,))
    assert isinstance(found, Branch) and found.start == tip


def test_missing_origin_knowledge_is_target_unless_selected_start_proves_the_base(
    repo: FakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tip = leave(repo, tmp_path, BRANCH)
    invalid = leave(repo, tmp_path, "other", extra=True)
    refs = repo.refs
    monkeypatch.setattr(repo, "refs", lambda names: tuple(entry for entry in refs(names)
                                                         if entry.name != "refs/remotes/origin/main"))
    assert isinstance(branch_refusal(repo, "tl-1", (tip,)), Branch)
    assert branch_refusal(repo, "tl-1", (invalid,)) == "target"


def test_unreadable_origin_ancestry_is_not_divergence(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    leave(repo, tmp_path, BRANCH)
    target = remote.advance("main", {"other": "landed\n"})
    assert repo.fetch().ok
    ancestor = repo.is_ancestor

    def read(a: str, b: str) -> bool:
        if b == target:
            raise GitUnavailable("cannot read origin main")
        return ancestor(a, b)

    monkeypatch.setattr(repo, "is_ancestor", read)
    with pytest.raises(GitUnavailable, match="cannot read origin main"):
        branch_refusal(repo, "tl-1", (target,))
