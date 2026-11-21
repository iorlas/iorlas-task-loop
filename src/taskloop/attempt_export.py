"""Read-only comparison evidence, one row per agent attempt.

NULL means unknown. t_* and c_* are token counts, never dollars; usage is a lower bound when incomplete.
chain_id is the first attempt reached through previous_attempt_id. rework_count counts repeats (check-driven or leftover)
through this row, excluding answer repairs. time_to_green_seconds measures that chain's first admission to
this row's latest passed checks; otherwise NULL. wall_seconds remains this agent attempt's admission to capture.
setup_seconds is the latest setup run's duration. check_seconds maps check names to durations in the latest
block of the latest checks attempt (unfinished durations are NULL, no recorded checks is an empty object).
The launched-input digest is not stored in factory.db; input_digest is the admitted input only.
"""

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
