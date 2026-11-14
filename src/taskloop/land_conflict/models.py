"""Immutable admission facts and explained outcomes."""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taskloop.attempt_loads import RetainedInputs
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.abort_models import Abort, AbortPhase
from taskloop.land_conflict.cleanup_models import Cleanup, CleanupPhase
from taskloop.land_conflict.release_models import Release
from taskloop.merge.models import Phase


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Request(Value):
    source: AttemptKey
    checks: AttemptKey
    repo_id: str
    backlog: str
    task_id: str
    tracker_root: str
    checked: str = Field(min_length=40, max_length=64)
    target: str = Field(min_length=40, max_length=64)
    deadline: float

    def matches(self, inputs: RetainedInputs) -> bool:
        return (self.source, self.repo_id, self.backlog, self.task_id, self.tracker_root, self.checked) == (
            inputs.key, inputs.repo_id, inputs.backlog, inputs.task_id, inputs.tracker_root, inputs.checked)


class Record(Value):
    key: AttemptKey
    request: Request
    inputs: RetainedInputs
    slot: str
    slot_path: str
    base: str
    admitted_at: float

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.request.matches(self.inputs) or self.key.reservation_generation < 1:
            raise ValueError("admission must retain its exact source and positive reservation generation")
        return self


class Slot(Value):
    name: str
    path: str
    generation: int
    head: str


class Outcome(StrEnum):
    ADMITTED = "admitted"
    RETAINED = "retained"
    SOURCE = "source"
    NOT_CHECKED = "not_checked"
    NOT_DONE = "not_done"
    LANDING = "landing"
    INPUT = "input"
    NO_SLOT = "no_slot"
    UNAVAILABLE = "unavailable"


class AdmissionRefused(Exception):
    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome


class Result(Value):
    outcome: Outcome
    explanation: str = Field(min_length=1)
    record: Record | None = None


class SavePhase(StrEnum):
    CAPTURE = "capture"
    OBJECT = "object"
    REF = "ref"
    COMPLETE = "complete"


class Save(Value):
    key: AttemptKey
    repo_id: str
    slot: str
    slot_path: Path
    gitdir: Path
    source: str = Field(min_length=40, max_length=64)
    target: str = Field(min_length=40, max_length=64)
    head: str = Field(min_length=40, max_length=64)
    merging: bool
    accepted: bool
    ref: str
    expected: str | None = None
    when: int
    message: str = Field(min_length=1)
    parents: tuple[str, ...] = Field(min_length=1, max_length=3)
    phase: SavePhase = SavePhase.CAPTURE
    tree: str | None = Field(default=None, min_length=40, max_length=64)
    commit: str | None = Field(default=None, min_length=40, max_length=64)
    abort: Abort | None = None
    cleanup: Cleanup | None = None
    release: Release | None = None

    @model_validator(mode="after")
    def consistent_release(self) -> Self:
        if self.release is not None and (
                self.cleanup is None or self.cleanup.phase is not CleanupPhase.COMPLETE
                or self.release.work != self.cleanup.work or self.release.before != self.cleanup.after):
            raise ValueError("release requires completed cleanup and the exact saved work")
        return self

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.cleanup is not None:
            cleanup = self.cleanup
            if self.phase is not SavePhase.COMPLETE:
                raise ValueError("cleanup requires completely retained work")
            if ((cleanup.work.attempt_id, cleanup.work.dispatch_token, cleanup.work.generation)
                    != (self.key.attempt_id, self.key.dispatch_token, self.key.reservation_generation)
                    or (cleanup.work.repo_id, cleanup.work.slot, cleanup.work.gitdir, cleanup.work.source, cleanup.work.target)
                    != (self.repo_id, self.slot_path, self.gitdir, self.source, self.target)):
                raise ValueError("cleanup must retain the exact saved merge identity")
            if self.accepted and (
                    self.merging or cleanup.work.phase is not Phase.COMPLETE or cleanup.work.result != self.commit
                    or self.head != self.commit or cleanup.before.head != self.commit
                    or cleanup.before.branch is not None or cleanup.before.merging
                    or cleanup.before.merge_head is not None or cleanup.before.index):
                raise ValueError("accepted cleanup requires the exact clean detached completed work")
            if self.merging and cleanup.phase is not CleanupPhase.EXCLUDE and (
                    self.abort is None or self.abort.phase is not AbortPhase.COMPLETE):
                raise ValueError("cleanup parking requires a completed abort")
        if self.abort is not None and (self.phase is not SavePhase.COMPLETE or self.accepted or not self.merging):
            raise ValueError("abort requires a completely retained unfinished merge")
        if self.abort is not None and (
                (self.abort.work.attempt_id, self.abort.work.dispatch_token, self.abort.work.generation)
                != (self.key.attempt_id, self.key.dispatch_token, self.key.reservation_generation)
                or (self.abort.work.repo_id, self.abort.work.slot, self.abort.work.gitdir, self.abort.work.source, self.abort.work.target)
                != (self.repo_id, self.slot_path, self.gitdir, self.source, self.target)):
            raise ValueError("abort must retain the exact saved merge identity")
        if self.expected is not None:
            raise ValueError("a conflict save creates its own ref")
        if self.phase is not SavePhase.CAPTURE and self.tree is None:
            raise ValueError("object creation requires a frozen tree")
        if self.phase in (SavePhase.REF, SavePhase.COMPLETE) and self.commit is None:
            raise ValueError("ref publication requires a recorded commit")
        if not self.accepted and not {self.source, self.target, self.head} <= set(self.parents):
            raise ValueError("unfinished work must retain both inputs and its observed HEAD")
        return self
