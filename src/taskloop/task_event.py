"""A deciding operation's typed task event, before storage ownership and currentness fences."""

from enum import StrEnum

from pydantic import model_validator

from taskloop.step import Step
from taskloop.task_event_cause import (
    AnswerCause,
    ChecksCause,
    DispositionCause,
    MergeCause,
    RejectionCause,
    RepeatCause,
    RunCause,
    StuckCause,
    StuckReason,
    TaskEventCause,
    Text,
    Value,
)


class EventStep(StrEnum):
    PLAN = "plan"
    IMPLEMENT = "implement"
    CHECK = "check"


class TaskEvent(Value):
    """`attempt_id` is held; `cause_id` and `step` identify the deciding attempt, possibly its checks attempt."""

    attempt_id: Text
    agent_step: Step
    cause_id: Text
    step: EventStep
    cause: TaskEventCause

    @model_validator(mode="after")
    def consistent(self) -> TaskEvent:
        checks = self.step is EventStep.CHECK
        if checks:
            if self.cause_id == self.attempt_id or self.agent_step is not Step.IMPLEMENT:
                raise ValueError("Checks require a distinct cause and their owning implement attempt")
            if isinstance(self.cause, (DispositionCause, RunCause, AnswerCause, RejectionCause, RepeatCause, MergeCause)):
                raise ValueError("An agent failure cannot be caused by checks")
        elif self.cause_id != self.attempt_id or self.step.value != self.agent_step.value:
            raise ValueError("Agent causality must identify the held attempt and its step")
        if isinstance(self.cause, ChecksCause) and not checks:
            raise ValueError("A checks failure requires checks causality")
        if isinstance(self.cause, StuckCause) and (self.cause.reason is StuckReason.CHECKS_REFUSED) != checks:
            raise ValueError("The stuck reason must belong to the causal attempt's step")
        if isinstance(self.cause, (RunCause, StuckCause)) and self.cause.stop is not None and self.cause.stop.attempt_id != self.cause_id:
            raise ValueError("The stop must identify the causal attempt")
        return self
