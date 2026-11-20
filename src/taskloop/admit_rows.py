"""Admission observations and validated stored facts."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from taskloop.attempt_types import AttemptKey
from taskloop.step import Step


@dataclass(frozen=True)
class Free:
    """An observed-free slot's HEAD, selected task source and recorded park destination."""

    name: str
    head: str
    source: str
    park_commit: str


class Task(BaseModel):
    """The previous attempt's task and whether that attempt is still current."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    backlog: str
    task_id: str
    tracker_root: str
    repo_id: str
    step: Step
    current: bool = Field(strict=False)
    end_commit: str | None


class Previous(BaseModel):
    """Repeat eligibility and the predecessor's retained admission choices."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    generation: int
    number: int
    adapter: str
    backlog: str
    task_id: str
    repo_id: str
    slot: str
    model: str
    effort: str
    access_policy: str
    repeated: bool = Field(strict=False)
    repeatable: bool = Field(strict=False)
    tracker_root: str
    seq: int
    slot_head: str
    step: Step
    label: str | None
    harness: str
    provider: str
    compaction_token_limit: int | None


class Current(BaseModel):
    """The task's latest attempt and its completion facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    attempt_id: str
    dispatch_token: str
    generation: int
    done: bool = Field(strict=False)
    step: Step
    end_commit: str | None
    tracker_root: str
    seq: int
    label: str | None

    @property
    def key(self) -> AttemptKey:
        return AttemptKey(self.attempt_id, self.dispatch_token, self.generation)
