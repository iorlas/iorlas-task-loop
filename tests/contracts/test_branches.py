"""Task branch names round trip without interpreting the bead suffix."""
import pytest

from tlkernel.branches import TASK, bead_of, task_branch


def test_task_branch():
    assert TASK == "task/"
    assert task_branch("tl-7i9k.41") == "task/tl-7i9k.41"
    assert task_branch("") == TASK


@pytest.mark.parametrize(("branch", "bead"), [
    ("task/tl-7i9k.41", "tl-7i9k.41"), ("task/a/b", "a/b"),
    ("task/", None), ("", None), ("main", None), ("tasks/a", None),
    ("refs/heads/task/a", None),
])
def test_bead_of(branch, bead):
    assert bead_of(branch) == bead
