"""The A/A and A/B export and the slot list: typed reads of a real factory.db that keep unknown values unknown."""

import sqlite3
from dataclasses import fields

from doubles import ENGINE, PIN_DIGEST

from taskloop import attempt_export, rows_render, slot_list
from taskloop.attempt_export_store import ExportRow, ExportStore
from taskloop.slot_list_store import SlotHold, SlotListStore

COLUMNS = [
    "task_id",
    "step",
    "number",
    "repeat_reason",
    "engine_digest",
    "workflow_digest",
    "workflow_sha",
    "harness",
    "model",
    "effort",
    "compaction_token_limit",
    "input_digest",
    "admitted_at",
    "ended_at",
    "wall_seconds",
    "disposition",
    "effect",
    "answer_kind",
    "rc",
    "timed_out",
    "turns",
    "t_in",
    "t_cached",
    "t_out",
    "c_in",
    "c_cached",
    "c_out",
    "usage_incomplete",
    "latest_checks_conclusion",
    "latest_checks_reason",
    "ran_model",
    "ran_effort",
    "harness_version",
]


def test_the_export_gives_one_row_per_attempt_with_its_identity_and_no_invented_numbers(registered: sqlite3.Connection) -> None:
    found = attempt_export.export(ExportStore(lambda: registered), None)
    assert isinstance(found, attempt_export.AttemptExport)
    (row,) = found.rows
    assert [each.name for each in fields(ExportRow)] == COLUMNS
    assert (row.task_id, row.step, row.number) == ("tl-1", "plan", 1)
    assert (row.engine_digest, row.workflow_digest) == (ENGINE, PIN_DIGEST)
    assert row.ended_at is None and row.wall_seconds is None and row.t_in is None  # not captured: unknown, not zero
    header, line = rows_render.lines(found)
    assert header.split(",") == COLUMNS and line.startswith("tl-1,plan,1,,")


def test_the_export_filters_by_backlog_and_the_wall_time_is_the_recorded_difference(registered: sqlite3.Connection) -> None:
    registered.execute("UPDATE attempt SET phase='captured',base_commit=slot_head,ended_at=admitted_at+2.5")
    store = ExportStore(lambda: registered)
    assert attempt_export.export(store, "other") == attempt_export.AttemptExport(())
    found = attempt_export.export(store, "tasks")
    assert isinstance(found, attempt_export.AttemptExport) and found.rows[0].wall_seconds == 2.5
    assert rows_render.records(found)[0]["usage_incomplete"] is None


def test_the_slot_list_shows_a_held_slot_with_its_attempt_and_a_free_one(registered: sqlite3.Connection) -> None:
    repo = registered.execute("SELECT repo_id FROM slot").fetchone()[0]
    registered.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s2','/slots/s2')", (repo,))
    found = slot_list.list_slots(SlotListStore(lambda: registered))
    assert isinstance(found, slot_list.SlotList)
    assert [(row.name, row.state, row.attempt_id) for row in found.rows] == [("s1", SlotHold.HELD, "attempt"), ("s2", SlotHold.FREE, None)]
    assert rows_render.records(found)[1]["attempt_id"] is None
