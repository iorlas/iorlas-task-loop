"""Best-effort wall-clock discontinuity evidence; never an input to runtime or scheduling."""

from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ClockContext(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"


class ClockDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


class ClockJump(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    context: ClockContext
    direction: ClockDirection
    wall_before: float
    wall_after: float
    monotonic_elapsed: float
    difference: float


def encode(jump: ClockJump) -> str:
    return jump.model_dump_json()


class ClockJumps:
    def __init__(
        self, context: ClockContext, wall: Callable[[], float], monotonic: Callable[[], float],
        write: Callable[[ClockJump], None],
    ) -> None:
        self.context, self.wall, self.monotonic, self.write = context, wall, monotonic, write
        self._wall, self._monotonic = wall(), monotonic()

    def sample(self) -> None:
        wall, monotonic = self.wall(), self.monotonic()
        before, elapsed = self._wall, monotonic - self._monotonic
        self._wall, self._monotonic = wall, monotonic
        difference = wall - before - elapsed
        if abs(difference) <= 1:
            return
        with suppress(Exception):  # evidence loss must never affect the observed operation
            self.write(ClockJump(
                context=self.context, direction=ClockDirection.FORWARD if difference > 0 else ClockDirection.BACKWARD,
                wall_before=before, wall_after=wall, monotonic_elapsed=elapsed, difference=difference,
            ))
