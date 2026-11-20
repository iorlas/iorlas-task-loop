"""Display recorded factory operations without deriving workflow state or elapsed time."""

from datetime import UTC, datetime

from taskloop.dash_model import OperationDetail
from taskloop.operation_evidence import OperationSample, OperationState


def project(samples: tuple[OperationSample, ...], step: str, number: int, *, past: bool) -> tuple[OperationDetail, ...]:
    found: list[OperationDetail] = []
    for sample in sorted(samples, key=lambda each: (each.started_at, each.operation)):
        try:
            started = datetime.fromtimestamp(sample.started_at, UTC).isoformat(timespec="milliseconds")
        except OverflowError, OSError, ValueError:
            continue
        elapsed = None
        if sample.state is not OperationState.ACTIVE:
            try:
                elapsed = int(sample.elapsed * 1000)
            except OverflowError:
                elapsed = int(sample.elapsed) * 1000
        found.append(
            OperationDetail(
                operation=sample.operation,
                step=step,
                n=number,
                past=past,
                kind=sample.kind,
                state=sample.state,
                started_at=started,
                elapsed_ms=elapsed,
            )
        )
    return tuple(found)
