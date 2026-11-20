"""Typed observations of factory effects; evidence failures never decide workflow outcomes."""

import math
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from taskloop.attempt_types import AttemptKey


class OperationKind(StrEnum):
    COMMIT = "commit"
    PUBLISH = "publish"
    CHECKS_START = "checks-start"


class OperationState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class OperationSample(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)

    operation: str = Field(pattern=r"^[a-f0-9]{32}$")
    attempt: str = Field(min_length=1)
    kind: OperationKind
    started_at: float
    elapsed: float = Field(ge=0)
    state: OperationState


class OperationObserver:
    def __init__(
        self,
        identity: Callable[[], tuple[str, str]],
        kind: OperationKind,
        clock: Callable[[], float],
        wall: Callable[[], float],
        write: Callable[[OperationSample], None],
    ) -> None:
        self.clock, self.write = clock, write
        self._sample: OperationSample | None = None
        self._origin = 0.0
        try:
            attempt, operation = identity()
            self._origin = clock()
            if not math.isfinite(self._origin):
                raise ValueError("Invalid monotonic origin")
            sample = OperationSample(
                operation=operation, attempt=attempt, kind=kind, started_at=wall(), elapsed=0.0, state=OperationState.ACTIVE
            )
            write(sample)
            self._sample = sample
        except Exception:
            pass

    def finish(self, state: OperationState) -> None:
        sample, self._sample = self._sample, None
        if sample is None:
            return
        try:
            if state is OperationState.ACTIVE:
                raise ValueError("Operation result must be final")
            final = OperationSample(
                operation=sample.operation,
                attempt=sample.attempt,
                kind=sample.kind,
                started_at=sample.started_at,
                elapsed=self.clock() - self._origin,
                state=state,
            )
            self.write(final)
        except Exception:
            pass  # preserve incomplete evidence, without extending it across a restart


type OperationTiming = Callable[[AttemptKey, OperationKind], OperationObserver]


@dataclass
class OperationResult:
    state: OperationState = OperationState.UNCERTAIN


@contextmanager
def measured(timing: OperationTiming | None, key: AttemptKey, kind: OperationKind) -> Generator[OperationResult]:
    observer = None
    with suppress(Exception):
        observer = None if timing is None else timing(key, kind)
    result = OperationResult()
    try:
        yield result
    except Exception:
        if observer is not None:
            observer.finish(OperationState.UNCERTAIN)
        raise
    else:
        if observer is not None:
            observer.finish(result.state)
