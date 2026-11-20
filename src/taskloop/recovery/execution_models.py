"""Durable execution progress and the identity carried by every recovery callback."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taskloop.attempt_types import AttemptKey
from taskloop.drain.models import Boundary, Identity


class Phase(StrEnum):
    INTENDED = "intended"
    REGISTERED = "registered"


class Execution(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    drain: Boundary
    phase: Phase = Phase.INTENDED
    worker: Identity | None = None
    revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent(self) -> Execution:
        if self.phase is Phase.INTENDED:
            valid = self.worker is None and self.revision is None
        else:
            valid = self.worker is not None and self.revision is not None
        if not valid:
            raise ValueError("Incomplete execution registration")
        return self


class Callback(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    key: AttemptKey
    generation: int = Field(ge=1)
    token: str = Field(min_length=1)
    owner: Identity
    worker: Identity
