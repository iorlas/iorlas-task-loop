"""Validated monotonic samples for one execution; display evidence only."""

import math
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DurationState(StrEnum):
    ACTIVE = "active"
    SEALED = "sealed"


class DurationSample(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)

    execution: str = Field(min_length=1)
    elapsed: float = Field(ge=0)
    command_offset: float | None = Field(default=None, ge=0)
    number: int = Field(ge=0)
    state: DurationState

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.command_offset is not None and self.command_offset > self.elapsed:
            raise ValueError("Command offset exceeds elapsed time")
        return self


class DurationObserver:
    def __init__(
        self, identity: Callable[[], str], clock: Callable[[], float], write: Callable[[DurationSample], None],
        invalidate: Callable[[], None],
    ) -> None:
        self.clock, self.write, self.invalidate = clock, write, invalidate
        self._stopped = False
        self._origin, self._last, self._number = 0.0, 0.0, 0
        self._command: float | None = None
        try:
            self._identity = identity()
            self._origin = clock()
            if not math.isfinite(self._origin):
                raise ValueError("Invalid monotonic origin")
            self._save(DurationState.ACTIVE)
        except Exception:
            self._invalid()

    def _invalid(self) -> None:
        self._stopped = True
        with suppress(Exception):
            self.invalidate()

    def _save(self, state: DurationState) -> None:
        sample = DurationSample(execution=self._identity, elapsed=self._last, command_offset=self._command,
                                number=self._number, state=state)
        try:
            self.write(sample)
        except Exception:
            self._stopped = True  # keep the previous complete snapshot; never join another observer's origin
        self._number += 1

    def sample(self, *, command: bool = False, seal: bool = False) -> None:
        if self._stopped:
            return
        try:
            elapsed = self.clock() - self._origin
            if not math.isfinite(elapsed) or elapsed < self._last:
                raise ValueError("Invalid monotonic observation")
            self._last = elapsed
            if command:
                self._command = elapsed
            self._save(DurationState.SEALED if seal else DurationState.ACTIVE)
            if seal:
                self._stopped = True
        except Exception:
            self._invalid()

    def seal(self) -> None:
        self.sample(seal=True)
