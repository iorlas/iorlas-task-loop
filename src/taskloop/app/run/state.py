"""The engine attributes bound to its current RunState."""
from typing import Any

from tlkernel import wire
from tlkernel.checkpoint import BriefSnap, Handoff, PlanStep, RunState, WriterSession
from tlkernel.plancheck import PlanData

from taskloop.app.look.state import LOOK_FIELDS

NOT_ATTRS = ("review",)  # the one field of another lane's type: reached as `engine.state.review` only


class StateField:
    """An engine attribute that lives in `engine.state`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        return self if obj is None else getattr(obj.state, self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj.state, self.name, value)


class StateAttrs:
    """Base of a class decorated with `carries_state`: declares the RunState fields as typed attributes (tests/run/test_state.py holds
    these equal to RunState's)."""

    plan_data: PlanData | None
    brief_hash: str
    snap: BriefSnap | None
    planner_ref: str
    planned: int
    replans: int
    fixes: int
    extra: int
    rebase_resets: int
    plan_log: list[PlanStep]
    done: list[str]
    accepted: list[int]
    accepted_new: list[str]
    denials: list[str]
    writer: WriterSession
    writer_family: str | None
    writer_fallback: bool
    fallback_lane: str
    render_stale: bool
    handoff: Handoff
    stage_tree: str
    pending_land_validation: str
    leftovers: list[dict[str, str]]
    followup_ids: dict[str, str]


def state_names() -> tuple[str, ...]:
    return tuple(name for name in wire.names(RunState) if name not in NOT_ATTRS)


def attr_names() -> tuple[str, ...]:
    """The RunState fields that are engine attributes: all but the look stage's, which it holds as `engine.look`."""
    return tuple(name for name in state_names() if name not in LOOK_FIELDS)


def carries_state[T](cls: type[T]) -> type[T]:
    for name in attr_names():
        setattr(cls, name, StateField(name))
    return cls


