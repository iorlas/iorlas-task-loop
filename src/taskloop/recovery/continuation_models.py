"""Explained results of saved-session continuation, including capture-only retry."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from taskloop.attempt_types import AttemptResult
from taskloop.recovery.callbacks import PendingExecution
from taskloop.recovery.models import Intent, Result


class State(StrEnum):
    LIVE = "live"
    COMPLETED = "completed"
    PENDING_CAPTURE = "pending_capture"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


class ContinuationResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", arbitrary_types_allowed=True)
    state: State
    explanation: str = Field(min_length=1)
    intent: Intent | None = None
    refusal: Result | None = None
    completion: AttemptResult | None = None
    pending: PendingExecution | None = None


def refused(result: Result) -> ContinuationResult:
    return ContinuationResult(state=State.REFUSED, explanation=result.explanation, intent=result.intent, refusal=result)
