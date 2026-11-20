"""Read-only setup measurements; any number of samples is a successful report."""

from pydantic import BaseModel, ConfigDict, Field

from taskloop.attempt_reads import StoreUnavailable
from taskloop.operations import Failed
from taskloop.setup_store import SetupSample, SetupStore


class SetupTimingReport(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    backlog: str
    rows: tuple[SetupSample, ...]
    sample_count: int = Field(ge=0, le=10)


def report(store: SetupStore, backlog: str) -> SetupTimingReport | Failed:
    try:
        rows = store.samples(backlog)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    return SetupTimingReport(backlog=backlog, rows=rows, sample_count=sum(row.duration_seconds is not None for row in rows))
