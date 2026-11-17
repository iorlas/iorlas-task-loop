"""Partial setup measurements succeed without deciding anything or changing execution state."""

import sqlite3
from dataclasses import replace

import pytest

from taskloop.command_conclusion import CommandConclusion
from taskloop.operations import Failed
from taskloop.setup_store import SetupRow, SetupStore
from taskloop.setup_timing import SetupTimingReport, report


@pytest.mark.parametrize(("end", "conclusion", "expected"), [
    (15.5, CommandConclusion.PASSED, 5.5), (10.0, CommandConclusion.PASSED, 0.0),
    (None, None, None), (15.5, CommandConclusion.FAILED, None), (9.0, CommandConclusion.PASSED, None),
    (float("inf"), CommandConclusion.PASSED, None), (float("nan"), CommandConclusion.PASSED, None),
    (None, CommandConclusion.PASSED, None),
])
def test_only_usable_recorded_differences_are_samples(
    end: float | None, conclusion: CommandConclusion | None, expected: float | None,
) -> None:
    row = SetupRow(1, "b" * 40, "d" * 64, 0, None, conclusion, 10.0, end)
    assert row.duration_seconds == expected
    assert replace(row, started_at=float("inf")).duration_seconds is None


@pytest.mark.parametrize(("count", "conclusion", "end", "usable"), [
    (0, None, None, 0), (3, None, None, 0), (4, CommandConclusion.FAILED, 20.0, 0),
    (2, CommandConclusion.PASSED, 9.0, 0), (1, CommandConclusion.PASSED, 10.0, 1),
    (10, CommandConclusion.PASSED, 20.0, 10),
])
def test_reports_any_partial_sample_count_without_writes(
    registered: sqlite3.Connection, count: int, conclusion: CommandConclusion | None, end: float | None, usable: int,
) -> None:
    registered.execute("UPDATE attempt SET step='implement',after_commit=slot_head")
    # Distinct setup owners share the fixture's configuration, never its environment.
    for index in range(count):
        identity = f"owner-{index}"
        registered.execute("""INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
            schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit,engine_digest,admitted_at)
            SELECT ?,?,generation,step,adapter,backlog,?,tracker_root,repo_id,slot,input_path,input_digest,
            schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit,engine_digest,admitted_at FROM attempt
            WHERE attempt_id='attempt'""", (identity, identity, identity))
        registered.execute("""INSERT INTO setup_run
            (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion)
            VALUES (?,1,?,1,?,?,10,?,?)""", (identity, identity, "b" * 40, "d" * 64, end, conclusion))
    before = registered.total_changes
    result = report(SetupStore(lambda: registered), "tasks")
    assert isinstance(result, SetupTimingReport)
    assert result.sample_count == usable and len(result.rows) == count
    assert set(result.model_dump()) == {"backlog", "rows", "sample_count"}
    expected = None if not usable else 0.0 if end == 10 else 10.0
    assert all(row.duration_seconds == expected for row in result.rows)
    assert registered.total_changes == before


def test_store_failure_is_reported() -> None:
    result = report(SetupStore(lambda: None), "tasks")
    assert isinstance(result, Failed) and (result.kind, result.reason) == ("unavailable", "store")
