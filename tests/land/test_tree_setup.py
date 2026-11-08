"""SETUPCHECK (tl-9un.31): after the reset, the worktree and branch are what the record says, or the bead fails before a worker starts."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from taskloop.app.wire.slotfx import FX
from tlland.tree import Tree
from tlwork.write.briefing import Briefing


class FakeGit:
    def __init__(self, branch: str, top: str) -> None:
        self._branch, self._top = branch, top

    def branch(self, wt: str) -> str:
        return self._branch

    def toplevel(self, wt: str) -> str:
        return self._top


def _tree(tmp_path: Path, branch: str, top: Path) -> Tree:
    blocked = lambda why, kind: RuntimeError(f"{kind}: {why}")  # noqa: E731
    return Tree(SimpleNamespace(wt=str(tmp_path), git=FakeGit(branch, str(top)), blocked_for=blocked), fx=FX)


def test_matching_branch_and_worktree_pass(tmp_path: Path) -> None:
    _tree(tmp_path, "task/t-1", tmp_path).verify("task/t-1")


def test_a_deviating_branch_fails_the_bead(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"FAULT_SLOT: .*branch main.*task/t-1"):
        _tree(tmp_path, "main", tmp_path).verify("task/t-1")


def test_a_deviating_worktree_fails_the_bead(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    with pytest.raises(RuntimeError, match=r"FAULT_SLOT: .*worktree"):
        _tree(tmp_path, "task/t-1", other).verify("task/t-1")


def test_the_writer_prompt_says_worktree_and_branch_exist() -> None:
    checker = SimpleNamespace(split=lambda: SimpleNamespace(divide=lambda pool: ([], [])))
    text = Briefing(SimpleNamespace(wt="/w/s1", branch="task/t-1", checker=checker, cfg=SimpleNamespace(checks=[]))).where("write")
    assert "/w/s1" in text and "task/t-1" in text and "exist" in text
