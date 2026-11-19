"""The A/A and A/B export query stays valid against the schema and keeps unknown values unknown."""

import sqlite3
from pathlib import Path

from doubles import ENGINE, PIN_DIGEST

EXPORT = (Path(__file__).resolve().parents[2] / "tools" / "attempt_export.sql").read_text()


def test_the_export_gives_one_row_per_attempt_with_its_identity_and_no_invented_numbers(registered: sqlite3.Connection) -> None:
    cursor = registered.execute(EXPORT)
    columns = [each[0] for each in cursor.description]
    (row,) = (dict(zip(columns, found, strict=True)) for found in cursor.fetchall())
    assert (row["task_id"], row["step"], row["number"]) == ("tl-1", "plan", 1)
    assert (row["engine_digest"], row["workflow_digest"]) == (ENGINE, PIN_DIGEST)
    assert row["ended_at"] is None and row["wall_seconds"] is None and row["t_in"] is None  # not captured: unknown, not zero
