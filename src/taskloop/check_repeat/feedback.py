"""Validated, immutable evidence passed from a completed check to an implement repeat."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from taskloop.attempt_types import AttemptKey
from taskloop.profile import MAX_ARG, MAX_ARGV, MAX_NAME, NAME_CHARS

TAIL_BYTES = 16 * 1024
TAIL_LINES = 100
RENDER_BYTES = 64 * 1024


class Availability(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


class CheckRepeatReason(StrEnum):
    FAILED_CHECK = "failed_check"


class FailedResult(StrEnum):
    FAILED = "failed"


class FeedbackReason(StrEnum):
    PROFILE = "check_profile"
    EVIDENCE = "check_feedback"


class CheckRepeatSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: CheckRepeatReason
    checks_id: str = Field(min_length=1)


def stored_source(value: object, reason: object) -> str | None:
    """The single persisted provenance codec; ordinary path repeats have no checks link."""
    if value is None and reason != CheckRepeatReason.FAILED_CHECK.value:
        return None
    return CheckRepeatSource.model_validate({"reason": reason, "checks_id": value}).checks_id


class OutputTail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    availability: Availability
    text: str = Field(default="", max_length=TAIL_BYTES)
    truncated: bool = False

    @model_validator(mode="after")
    def consistent(self) -> OutputTail:
        if (self.availability is Availability.AVAILABLE) != bool(self.text):
            raise ValueError("Only available output contains text")
        return self


class FailedCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: AttemptKey
    block: int = Field(ge=1)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    name: str = Field(min_length=1, max_length=MAX_NAME)
    argv: tuple[Annotated[str, Field(min_length=1, max_length=MAX_ARG)], ...] = Field(min_length=1, max_length=MAX_ARGV)
    result: FailedResult = FailedResult.FAILED
    rc: int
    output: OutputTail

    @field_validator("name")
    @classmethod
    def named(cls, value: str) -> str:
        if value.startswith((".", "-")) or set(value) - NAME_CHARS:
            raise ValueError("Invalid check name")
        return value

    @field_validator("argv")
    @classmethod
    def arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not arg.isprintable() or not arg.strip(" " if index else None) for index, arg in enumerate(value)):
            raise ValueError("Invalid check argv")
        return value

    @field_validator("rc")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("A failed check needs a nonzero exit")
        return value


def escaped(text: str) -> str:
    """Lossless printable evidence, without the short filename display cap."""
    return "".join(char if char.isprintable() or char == "\n" else ascii(char)[1:-1] for char in text)


def output_text(tail: OutputTail) -> str:
    if tail.availability is Availability.UNAVAILABLE:
        return "Output unavailable: the retained check output could not be read."
    if tail.availability is Availability.EMPTY:
        return "Output empty: the check produced no retained output."
    # Reserve space for the cut notice and every line prefix before limiting the escaped evidence.
    data = escaped(tail.text).encode("utf-8")
    cap = RENDER_BYTES - 4 * TAIL_LINES - 128
    cut = tail.truncated or len(data) > cap
    kept = data[-cap:].decode("utf-8", "replace")
    text = "\n".join("| " + line for line in kept.split("\n"))
    return ("[cut prefix: showing the retained output tail]\n" if cut else "") + text
