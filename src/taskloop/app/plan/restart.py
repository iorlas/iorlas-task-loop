"""The plan section keeps extra, rebase_resets, brief_hash, snap and planner_ref on restart."""
from typing import TypedDict

from tlkernel.checkpoint import BriefSnap, RunState


class Kept(TypedDict):
    """The plan fields that belong to the bead across attempts."""

    extra: int
    rebase_resets: int
    brief_hash: str
    snap: BriefSnap | None
    planner_ref: str


def keep(state: RunState) -> Kept:
    """Keep extra, rebase_resets, brief_hash, snap and planner_ref."""
    return {"extra": state.extra, "rebase_resets": state.rebase_resets, "brief_hash": state.brief_hash,
            "snap": state.snap, "planner_ref": state.planner_ref}
