"""The land section keeps pending_land_validation, leftovers and followup_ids on restart."""
from typing import TypedDict

from tlkernel.checkpoint import RunState


class Kept(TypedDict):
    """The land fields that survive a fresh attempt."""

    pending_land_validation: str
    leftovers: list[dict[str, str]]
    followup_ids: dict[str, str]


def keep(state: RunState) -> Kept:
    """Keep pending_land_validation, leftovers and followup_ids."""
    return {"pending_land_validation": state.pending_land_validation, "leftovers": state.leftovers,
            "followup_ids": state.followup_ids}


def pin_validation(state: RunState, step: str, feedback: str) -> tuple[str, str]:
    """A fix, a re-plan or an interrupted recovery must never turn a pending validation into a direct-to-land checkpoint."""
    return ("land-verify-red", state.pending_land_validation) if state.pending_land_validation else (step, feedback)
