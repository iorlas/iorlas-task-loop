"""The fenced identity of an earlier agent attempt selected for a task's next input."""

from pydantic import BaseModel, ConfigDict

from taskloop.attempt_types import AttemptKey, Step


class EarlierAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    key: AttemptKey
    revision: int
    repo_id: str
    backlog: str
    task_id: str
    tracker_root: str
    slot: str
    step: Step
    end_commit: str | None
