"""Names of branches that belong to a bead."""
from typing import Final

TASK: Final = "task/"


def task_branch(bead: str) -> str:
    return TASK + bead


def bead_of(branch: str) -> str | None:
    if not branch.startswith(TASK):
        return None
    return branch[len(TASK):] or None
