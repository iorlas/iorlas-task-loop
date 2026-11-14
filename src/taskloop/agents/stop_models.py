"""Validated durable facts of a factory initiated agent stop; no process-library types."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StopCause(StrEnum):
    DEADLINE = "deadline"
    FIRST_OUTPUT = "first_output"
    INACTIVITY = "inactivity"
    STALLED = "stalled"
    ANSWER = "answer"
    POLICY = "policy"
    LIMIT = "limit"
    CREDIT = "credit"
    AUTHENTICATION = "authentication"
    NETWORK = "network"
    WATCHDOG = "watchdog"
    ENTRY_SIGNAL = "entry_signal"
    INTERRUPT = "interrupt"
    PARENT_LOST = "parent_lost"
    CALLER_EXIT = "caller_exit"


class StopOperation(StrEnum):
    EXECUTE = "execute"


class StopPhase(StrEnum):
    REQUESTED = "requested"
    REPORTED = "reported"
    OBSERVED_GONE = "observed_gone"


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pid: int = Field(gt=0)
    pgid: int = Field(gt=0)
    start: str = Field(min_length=1, max_length=200)
    boot: str = Field(min_length=1, max_length=200)


class Survivor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pid: int = Field(gt=0)
    start: str | None = Field(default=None, max_length=200)


class StopProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    term_attempted: bool
    term_delivered: bool
    kill_attempted: bool
    kill_delivered: bool
    survivors: tuple[Survivor, ...]
    error: bool

    @model_validator(mode="after")
    def consistent(self) -> StopProof:
        if (self.term_delivered and not self.term_attempted) or (self.kill_delivered and not self.kill_attempted):
            raise ValueError("A delivered signal must have been attempted")
        return self


class AgentStop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    attempt_id: str
    dispatch_token: str
    generation: int = Field(ge=1)
    entry: Identity
    agent: Identity
    operation: StopOperation = StopOperation.EXECUTE
    cause: StopCause
    requested_signal: int = Field(gt=0, le=127)
    trigger_signal: int | None = Field(default=None, gt=0, le=127)
    requested_at: float
    phase: StopPhase = StopPhase.REQUESTED
    reported_at: float | None = None
    proof: StopProof | None = None
    observed_gone_at: float | None = None

    @model_validator(mode="after")
    def consistent(self) -> AgentStop:
        if (self.proof is None) != (self.reported_at is None):
            raise ValueError("A reported stop requires its report and time")
        if self.phase == StopPhase.REQUESTED and self.proof is not None:
            raise ValueError("An intent cannot contain a report")
        if self.phase == StopPhase.REPORTED and self.proof is None:
            raise ValueError("A reported stop requires its report")
        if (self.phase == StopPhase.OBSERVED_GONE) != (self.observed_gone_at is not None):
            raise ValueError("A gone observation requires its time")
        return self


def encode(record: AgentStop) -> str:
    return record.model_dump_json()


def decode(data: str) -> AgentStop:
    return AgentStop.model_validate_json(data)
