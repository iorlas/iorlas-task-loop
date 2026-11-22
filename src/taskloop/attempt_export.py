"""Read-only comparison evidence, one row per agent attempt.

NULL means unknown. t_* and c_* are token counts, never dollars; usage is a lower bound when incomplete.
chain_id is the first attempt reached through previous_attempt_id. rework_count counts the failed-check repeats through this
row; repair_count the answer repairs (a repair is not rework). time_to_green_seconds measures that chain's first admission to
this row's latest passed checks; otherwise NULL. task_total_seconds measures the task's first attempt admission (its plan) to
this row's latest passed checks across steps, the task's attempts in `seq` order being the only link of plan to implement;
otherwise NULL. wall_seconds remains this agent attempt's admission to capture. failed_checks names the checks of the latest
block that did not pass (an empty list: none, or none recorded). hold_text is the stored hold's explanation (NULL: no hold or none given).
setup_seconds is the latest setup run's duration. check_seconds maps check names to durations in the latest
block of the latest checks attempt (unfinished durations are NULL, no recorded checks is an empty object).
input_digest is the admitted input, launched_input_digest the input actually launched (NULL: never dispatched). base_commit is the slot
HEAD the attempt started from; changed_files and changed_lines are its diff to its commit (NULL: no committed verdict).
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
