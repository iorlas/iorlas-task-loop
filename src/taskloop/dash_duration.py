"""Saved execution durations for every dashboard read; wall time never supplies a measurement."""

from pydantic import BaseModel, ConfigDict

from taskloop.attempt_reads import AttemptRow, StoreConnection, StoreUnavailable
from taskloop.attempt_types import AttemptResult
from taskloop.duration_evidence import DurationSample, DurationState
from taskloop.evidence_files import EvidenceFiles
from taskloop.recovery.state_store import RecoveryReads


class Duration(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    execution: str
    number: int
    elapsed_ms: int
    quiet_ms: int | None
    frozen: bool


def _milliseconds(seconds: float) -> int:
    try:
        return int(seconds * 1000)
    except OverflowError:
        # At this magnitude every representable finite second value is already an integer.
        return int(seconds) * 1000


def project(sample: DurationSample | None, *, terminal: bool) -> Duration | None:
    if sample is None or (terminal and sample.state is not DurationState.SEALED):
        return None
    frozen = terminal or sample.state is DurationState.SEALED
    quiet = sample.elapsed - (sample.command_offset or 0)
    return Duration(execution=sample.execution, number=sample.number, elapsed_ms=_milliseconds(sample.elapsed),
                    quiet_ms=None if frozen else _milliseconds(quiet), frozen=frozen)


def read(store: StoreConnection, files: EvidenceFiles, row: AttemptRow, result: AttemptResult) -> Duration | None:
    try:
        execution = RecoveryReads(store.connect).execution(row.key)
    except StoreUnavailable:
        return None
    return project(files.duration(row.key, execution), terminal=result.status == "collected" or not row.held)
