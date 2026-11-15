"""The single structured TaskEvent codec and its existing hold-reason projection. No reason parser."""

from taskloop.task_event import TaskEvent
from taskloop.task_event_cause import (
    AnswerCause,
    ChecksCause,
    DispositionCause,
    LandCause,
    MergeCause,
    RejectionCause,
    RepeatCause,
    RoundCause,
    RunCause,
    StuckCause,
)


def encode(event: TaskEvent) -> str:
    return event.model_dump_json()


def decode(text: str) -> TaskEvent:
    return TaskEvent.model_validate_json(text, strict=True)


def reason(event: TaskEvent) -> str:
    """Keep exact prefixes, check names and terminal distinctions at the existing reason boundary."""
    cause = event.cause
    match cause:
        case DispositionCause():
            word = cause.reason.value
        case RunCause():
            word = f"run:{cause.reason.value}"
        case AnswerCause():
            word = f"answer:{cause.reason.value}"
        case RejectionCause():
            word = f"rejected:{cause.reason.value}"
        case ChecksCause():
            word = _checks(cause)
        case StuckCause():
            word = f"stuck:{cause.reason.value}"
        case RepeatCause():
            word = "repeats_exhausted" + (f":{cause.leftovers.reason.value}" if cause.leftovers is not None else "")
        case MergeCause():
            word = f"merge:{cause.reason.value}"
        case LandCause():
            word = f"land:{cause.reason.value}"
        case RoundCause():
            word = cause.reason.value
    return f"failed:{word}" if isinstance(cause, (DispositionCause, RunCause, AnswerCause, RejectionCause, ChecksCause)) else word


def _checks(cause: ChecksCause) -> str:
    if cause.reason is not None:
        return cause.reason.value
    if cause.check is not None:
        return f"{cause.check.name}:{cause.check.conclusion.value}"
    if cause.setup is not None:
        return f"setup:{cause.setup.value}"
    if cause.profile is not None:
        return f"profile:{cause.profile.value}"
    raise ValueError("Checks require a deciding failure")
