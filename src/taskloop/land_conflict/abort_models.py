"""Recorded checkout expectations for the conflict slice's abort effect."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from taskloop.merge.models import Work


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Checkout(Value):
    repo_id: str
    root: Path
    path: Path
    gitdir: Path
    head: str
    branch: str | None
    merging: bool
    merge_head: str | None
    index: tuple[str, ...]
    files: dict[str, tuple[str, str]]


class AbortPhase(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


class Abort(Value):
    work: Work
    before: Checkout
    after: Checkout
    phase: AbortPhase = AbortPhase.PENDING


def transition(previous: Abort | None, updated: Abort | None) -> bool:
    if previous is None:
        return updated is not None and updated.phase is AbortPhase.PENDING
    return (updated is not None and previous.phase is AbortPhase.PENDING and updated.phase is AbortPhase.COMPLETE
            and previous.model_dump(exclude={"phase"}) == updated.model_dump(exclude={"phase"}))
