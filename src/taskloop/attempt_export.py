"""The attempt export: every agent attempt's comparison row, read-only; any number of rows is a successful report."""

from dataclasses import dataclass

from taskloop.attempt_export_store import ExportRow, ExportStore
from taskloop.attempt_reads import StoreUnavailable
from taskloop.operations import Failed


@dataclass(frozen=True)
class AttemptExport:
    rows: tuple[ExportRow, ...]


def export(store: ExportStore, backlog: str | None) -> AttemptExport | Failed:
    try:
        return AttemptExport(store.attempts(backlog))
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
