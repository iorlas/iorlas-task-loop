"""The shared vocabulary for one setup or check command's conclusion."""

from enum import StrEnum
from typing import overload

from pydantic import TypeAdapter


class CommandConclusion(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    LINGERING = "lingering"
    DIRTY = "dirty"
    UNDEFINED = "undefined"
    INTERRUPTED = "interrupted"


# Setup commands must be defined; individual checks also report missing required names.
SETUP_CONCLUSIONS = tuple(each for each in CommandConclusion if each is not CommandConclusion.UNDEFINED)


_ADAPTER = TypeAdapter(CommandConclusion)


def decode(value: object) -> CommandConclusion | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid command conclusion type")
    return _ADAPTER.validate_python(value)


@overload
def encode(value: CommandConclusion) -> str: ...


@overload
def encode(value: None) -> None: ...


def encode(value: CommandConclusion | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, CommandConclusion):
        raise ValueError("Expected a command conclusion")
    return value.value
