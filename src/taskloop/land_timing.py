"""Land timing and replacement-cause codecs at the storage boundary."""

from enum import StrEnum

from pydantic import FiniteFloat, TypeAdapter, ValidationError

from taskloop.attempt_reads import StoreUnavailable


class Phase(StrEnum):
    VALIDATION = "validation"
    RELEASE = "release"
    DELIVERY = "delivery"
    CLOSE = "close"


class RetryCause(StrEnum):
    FAILED = "failed"
    MOVED = "moved"
    GONE = "gone"
    WITHDRAWN = "withdrawn"
    ABANDONED = "abandoned"


TIME = TypeAdapter(FiniteFloat)


def time(value: object) -> float:
    """A finite wall-clock time; phases need not follow wall-clock order."""
    return TIME.validate_python(value, strict=True)


def stored_time(value: object) -> float:
    try:
        return time(value)
    except ValidationError as error:
        raise StoreUnavailable("Malformed stored land time") from error


def stored_start(value: object) -> float | None:
    return None if value is None else stored_time(value)


def stored_cause(value: object) -> RetryCause | None:
    if value is None:
        return None
    try:
        return RetryCause(value)
    except ValueError as error:
        raise StoreUnavailable("Malformed stored land retry cause") from error


def start_column(phase: Phase) -> str:
    return f"{phase.value}_started_at"
