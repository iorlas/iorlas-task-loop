"""Recovery observations and durable ownership; no execution state."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from taskloop.attempt_types import AttemptKey, AttemptRecord, EntryIdentity
from taskloop.drain.models import Boundary, Identity, Seen


class Outcome(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    INELIGIBLE = "ineligible"
    UNRESOLVED = "unresolved"
    CHANGED = "changed"
    OCCUPIED = "occupied"
    DRAINING = "draining"
    EXPIRED = "expired"
    CLAIM_LOST = "claim_lost"
    CLAIM_UNKNOWN = "claim_unknown"
    CUSTODY_BUSY = "custody_busy"
    UNAVAILABLE = "unavailable"


class ClaimState(StrEnum):
    OWNED = "owned"
    LOST = "lost"
    UNKNOWN = "unknown"


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class Claim(Model):
    state: ClaimState
    explanation: str = Field(min_length=1)


class ProcessObservation(Model):
    seen: Seen
    explanation: str = Field(min_length=1)


class Intent(Model):
    key: AttemptKey
    generation: int = Field(ge=1)
    token: str = Field(min_length=1)
    owner: Identity
    attempt_revision: int = Field(ge=0)
    session: str = Field(min_length=1)
    entry: EntryIdentity
    worker: Identity


class Result(Model):
    outcome: Outcome
    explanation: str = Field(min_length=1)
    intent: Intent | None = None


class Snapshot(Model):
    attempt: AttemptRecord
    drain: Boundary
    intent: Intent | None = None


class Observations(Model):
    snapshot: Snapshot
    entry: ProcessObservation
    worker: ProcessObservation
    owner: ProcessObservation | None = None
    claim: Claim
