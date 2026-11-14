"""Typed admission and frozen context for one answer repair."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from taskloop.answer_failures import AnswerFailureData


class RepairContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str = Field(strict=True, min_length=1, pattern=r"^[^\s-][^\s]*$")
    base_commit: str = Field(strict=True, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    failure: AnswerFailureData


class RepairOutcome(StrEnum):
    ADMITTED = "admitted"
    EXISTING = "existing"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"
