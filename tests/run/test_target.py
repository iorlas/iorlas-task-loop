"""STAGERUN (tl-9un.52): `tl run-task` takes a bead, or the task branch or PR of one, and names the bead it runs."""
from argparse import Namespace

import pytest

from taskloop.app.run.target import resolve
from tlkernel.procport import Ran


class FakeSpawner:
    def __init__(self, out: str = "", exit: int = 0) -> None:
        self.argv: list[str] = []
        self._ran = Ran(exit=exit, out=out, err="no such pr")

    def run(self, argv: list[str], *, cwd: str | None = None) -> Ran:
        self.argv = argv
        return self._ran


def _args(**kw: object) -> Namespace:
    return Namespace(**{"id": None, "branch": None, "pr": None, **kw})


def test_a_bead_id_is_itself() -> None:
    assert resolve(_args(id="t-1"), FakeSpawner(), ".") == "t-1"


def test_a_task_branch_names_its_bead() -> None:
    assert resolve(_args(branch="task/t-9"), FakeSpawner(), ".") == "t-9"


def test_a_pr_names_the_bead_of_its_head_branch() -> None:
    sp = FakeSpawner('{"headRefName": "task/t-7"}')
    assert resolve(_args(pr=12), sp, ".") == "t-7"
    assert sp.argv[:4] == ["gh", "pr", "view", "12"]


@pytest.mark.parametrize("a", [_args(), _args(id="t-1", pr=3), _args(branch="task/t-1", pr=3)])
def test_exactly_one_of_bead_branch_pr(a: Namespace) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        resolve(a, FakeSpawner(), ".")


def test_a_branch_that_is_no_task_branch_is_refused_with_the_reason() -> None:
    with pytest.raises(ValueError, match="not a task branch"):
        resolve(_args(branch="feature/x"), FakeSpawner(), ".")


def test_an_unreadable_pr_is_refused() -> None:
    with pytest.raises(ValueError, match="PR 5"):
        resolve(_args(pr=5), FakeSpawner(exit=1), ".")
