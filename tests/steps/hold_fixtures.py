"""Explicit validated events shared by hold producers and display fixtures."""

from taskloop.command_conclusion import CommandConclusion
from taskloop.hold_store import HoldRow, Labels
from taskloop.step import Step
from taskloop.task_event import EventStep, TaskEvent
from taskloop.task_event_cause import (
    AnswerCause,
    AnswerReason,
    ChecksCause,
    ChecksReason,
    DispositionCause,
    DispositionReason,
    FailedCheck,
    LandCause,
    LandReason,
    Leftovers,
    MergeCause,
    MergeReason,
    ProfileReason,
    RejectionCause,
    RejectionReason,
    RepeatCause,
    RepeatReason,
    RoundCause,
    RoundReason,
    RunCause,
    RunReason,
    StuckCause,
    StuckReason,
    TaskEventCause,
)
from taskloop.task_event_codec import encode, reason


def event(cause: TaskEventCause | None = None, attempt_id: str = "a", cause_id: str | None = None, step: Step = Step.PLAN) -> TaskEvent:
    checks = cause_id is not None and cause_id != attempt_id
    return TaskEvent(
        attempt_id=attempt_id,
        cause_id=cause_id or attempt_id,
        agent_step=Step.IMPLEMENT if checks else step,
        step=EventStep.CHECK if checks else EventStep(step),
        cause=cause or DispositionCause(reason=DispositionReason.NEEDS_OWNER, explanation="Owner decision required."),
    )


def causes() -> tuple[TaskEventCause, ...]:
    """A finite set of real causes for parameterized presentation tests, indexed by the owning projection."""
    return (
        *(DispositionCause(reason=each, explanation="Owner decision required.") for each in DispositionReason),
        *(RunCause(reason=each, deadline=100.0) for each in RunReason),
        *(AnswerCause(reason=each) for each in AnswerReason),
        *(RejectionCause(reason=each) for each in RejectionReason),
        *(StuckCause(reason=each) for each in StuckReason),
        *(RoundCause(reason=each) for each in RoundReason),
        *(MergeCause(reason=each, explanation="Resolve retained merge work.") for each in MergeReason),
        *(LandCause(reason=each, explanation="Automatic land was refused.") for each in LandReason),
        RepeatCause(),
        *(RepeatCause(leftovers=Leftovers(reason=each, paths=("a.py",))) for each in RepeatReason),
        *(ChecksCause(reason=each) for each in ChecksReason),
        *(ChecksCause(profile=each) for each in ProfileReason),
        *(
            ChecksCause(check=FailedCheck(name=name, conclusion=conclusion))
            for name in ("test", "check")
            for conclusion in (CommandConclusion.FAILED, CommandConclusion.LINGERING)
        ),
    )


def event_for(word: str, attempt_id: str = "a", cause_id: str | None = None, step: Step = Step.PLAN) -> TaskEvent:
    """Look up a fixture by its exact canonical projection; never accept an invented reason."""
    for cause in causes():
        checking = isinstance(cause, ChecksCause) or (isinstance(cause, StuckCause) and cause.reason is StuckReason.CHECKS_REFUSED)
        candidate = event(cause, cause_id="checks" if checking else None)
        if reason(candidate) == word:
            return event(cause, attempt_id, cause_id or ("checks" if checking else None), step)
    raise ValueError(f"No typed fixture for {word}")


def events() -> tuple[TaskEvent, ...]:
    return tuple(
        event(
            cause,
            cause_id="checks"
            if isinstance(cause, ChecksCause) or (isinstance(cause, StuckCause) and cause.reason is StuckReason.CHECKS_REFUSED)
            else None,
        )
        for cause in causes()
    )


def row(label: str = "auto", labels: Labels = "moved") -> HoldRow:
    return HoldRow(
        event=event(),
        held_at=10.0,
        labels=labels,
        labelled_at=11.0,
        commenting_at=12.0,
        commented_at=13.0,
        cleared_at=None,
        rev=4,
        backlog="tasks",
        task_id="tl-1",
        tracker_root="/tracker",
        label=label,
    )


STUCK = StuckCause(reason=StuckReason.ENTRY_LOST)
STUCK_JSON = encode(event(STUCK, "attempt"))
STUCK_SQL = f"INSERT INTO task_hold(attempt_id,event,held_at) VALUES('attempt','{STUCK_JSON}',10)"
