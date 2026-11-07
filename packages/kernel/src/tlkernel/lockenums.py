"""The lock owner's vocabulary."""
from enum import StrEnum


class LockWhat(StrEnum):
    LAND = "land"
    REVIEW = "review"
    AREA = "area"
    SLOT_TAKE = "slot_take"
    WORKTREE = "worktree"
    RELEASE = "release"
    LOOP = "loop_run"
    RESOURCE = "resource"
