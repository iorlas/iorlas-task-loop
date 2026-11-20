"""The agent-step vocabulary and its persisted text codec."""

from enum import StrEnum
from typing import Final

ATTEMPTS: Final = 3  # attempts of one step at most (2 repeats); always compared as `number >= ATTEMPTS`


class Step(StrEnum):
    PLAN = "plan"
    IMPLEMENT = "implement"


def decode_step(text: str) -> Step:
    """Accept only an exact agent-step spelling."""
    return Step(text)


def encode_step(step: Step) -> str:
    return step.value
