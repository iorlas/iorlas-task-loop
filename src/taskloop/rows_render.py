"""The two read-only row listings' text: the attempt export as CSV (NULL empty) and the slot list, and their JSON arrays."""

import csv
import io
import json
from dataclasses import asdict, fields

from taskloop.attempt_export import AttemptExport
from taskloop.attempt_export_store import ExportRow
from taskloop.slot_list import SlotList

NEWLINE = "\n"
type Rows = AttemptExport | SlotList


def records(result: Rows) -> list[dict[str, object]]:
    """The JSON array: one object per row, NULL as null."""
    return [asdict(row) for row in result.rows]


def lines(result: Rows) -> list[str]:
    if isinstance(result, SlotList):
        return [f"{row.name}\t{row.state}\t{row.attempt_id or '-'}\t{row.repo_id}\t{row.path}" for row in result.rows]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator=NEWLINE)
    writer.writerow(each.name for each in fields(ExportRow))
    writer.writerows(
        [json.dumps(value, sort_keys=True) if isinstance(value, dict) else "" if value is None else value for value in asdict(row).values()]
        for row in result.rows
    )
    return out.getvalue().rstrip(NEWLINE).split(NEWLINE)
