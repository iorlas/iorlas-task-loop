"""Validated merge records and typed results; no display-text interpretation."""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taskloop.agents.settings import AgentSetting
from taskloop.drain.models import Identity

PREFIX = "merge:"


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Phase(StrEnum):
    FETCH = "fetch"
    SETUP = "setup"
    START = "start"
    RESOLVE = "resolve"
    FINISH = "finish"
    ATTACH = "attach"
    COMPLETE = "complete"
    TERMINAL = "terminal"


class Reason(StrEnum):
    TARGET = "target"
    DIVERGED = "branch_diverged"
    MOVED = "branch_moved"
    SLOT = "slot_moved"
    UNSUPPORTED = "unsupported_conflict"
    OWNER = "needs_owner"
    EXHAUSTED = "exhausted"
    INVALID = "invalid_resolution"
    EXPIRED = "expired"
    GIT = "git"
    RUNNING = "running"
    UNKNOWN = "unknown"


class Disposition(StrEnum):
    RESOLVED = "resolved"
    INCOMPLETE = "incomplete"
    OWNER = "needs_owner"


class Answer(Value):
    disposition: Disposition
    paths: tuple[str, ...]
    explanation: str = Field(min_length=1)


class Artifact(Value):
    path: str
    digest: str


class Execution(Value):
    number: int = Field(ge=1, le=3)
    worker: Identity | None = None
    session: str | None = None
    session_conflict: bool = False
    rc: int | None = None
    timed_out: bool = False
    ended: bool = False
    reviewed: bool = False
    answer: Answer | None = None
    input: Artifact | None = None
    evidence: tuple[Artifact, ...] = ()
    capturing: bool = False
    explanation: str = ""


class Work(Value):
    attempt_id: str
    dispatch_token: str
    generation: int
    task_id: str
    repo_id: str
    root: Path
    slot: Path
    gitdir: Path
    base: str
    source: str
    target: str | None = None
    # None is the detached continuation used by a consumer that keeps its checked branch unchanged.
    branch: str | None
    deadline: float
    setting: AgentSetting
    input_path: str
    input_digest: str
    phase: Phase = Phase.FETCH
    conflicts: tuple[str, ...] = ()
    baseline: str | None = None
    result: str | None = None
    executions: tuple[Execution, ...] = Field(default=(), max_length=3)
    reason: Reason | None = None
    explanation: str = "Main moved; the factory is merging it while retaining the task's work."

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.phase not in (Phase.FETCH, Phase.TERMINAL) and self.target is None:
            raise ValueError("a started merge requires its immutable target")
        if self.phase in (Phase.ATTACH, Phase.COMPLETE) and self.result is None:
            raise ValueError("acceptance requires a prepared result")
        if self.phase is Phase.TERMINAL and self.reason is None:
            raise ValueError("a terminal merge requires its cause")
        if tuple(each.number for each in self.executions) != tuple(range(1, len(self.executions) + 1)):
            raise ValueError("resolution executions must retain their order")
        return self


class Completed(Value):
    commit: str
    source: str
    target: str
    explanation: str


class InProgress(Value):
    reason: Reason
    explanation: str


class Unavailable(Value):
    reason: Reason
    explanation: str


class Terminal(Value):
    reason: Reason
    explanation: str


type Result = Completed | InProgress | Unavailable | Terminal
type Waiting = InProgress | Unavailable | Terminal


def encode(work: Work) -> str:
    """One codec for the stored record, including all closed vocabularies."""
    return work.model_dump_json()


def decode(data: str) -> Work:
    return Work.model_validate_json(data)
