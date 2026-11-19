"""What the run says about a NEW task's first attempt: where it starts and which workflow file it reads. A task already
under way keeps what it was admitted with, so these never apply to an advance, a repeat or a relaunch."""

from pydantic import field_validator

from taskloop.step import Step
from taskloop.workflow import Input
from taskloop.workflow_read import DEFAULT


class NewTask(Input):
    start: Step | None = None  # None is the first step (plan); implement needs a plan committed at the source commit
    workflow: str = DEFAULT  # `.task-loop/workflows/<workflow>.toml` at the task's source commit

    @field_validator("start")
    @classmethod
    def implement_only(cls, value: Step | None) -> Step | None:
        if value is Step.PLAN:
            raise ValueError("a task starts at the plan step by default; only implement can be named")
        return value

    @field_validator("workflow")
    @classmethod
    def file_name(cls, value: str) -> str:
        """A plain lowercase file name: letters, digits, `-` and `_`, so it can never name a path, a ref or a flag."""
        if not (value.isascii() and value.replace("-", "").replace("_", "").isalnum() and value == value.lower() and value[0].isalnum()):
            raise ValueError("a workflow is a plain file name of lowercase letters, digits, '-' and '_'")
        return value

    @property
    def given(self) -> bool:
        """The run named something other than the defaults."""
        return self != NewTask()
