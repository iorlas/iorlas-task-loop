"""Task detail retains the deciding hold snapshot after clearing or abandoning its chain."""

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import checking, factory
from hold_fixtures import event

from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.dash_model import Comment, Fields, Ready, TaskDetail
from taskloop.dash_server import _json
from taskloop.dash_task import TaskPorts, build_task
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.step import Step
from taskloop.task_event_cause import ChecksCause, ChecksReason, DispositionCause, DispositionReason

__all__ = ["checking", "factory"]


class Tracker:
    def ready(self) -> tuple[Ready, ...]:
        return ()

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {}

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        return None

    def notice(self) -> str | None:
        return None


def detail(con: sqlite3.Connection, tmp_path: Path) -> TaskDetail:
    reads = StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: 10, lambda _key: None, lambda: "boot")
    result = build_task(TaskPorts(reads, EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(result, TaskDetail)
    return result


@pytest.mark.parametrize("checks", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_stored_causes_follow_the_deciding_row_and_survive_history(
    checking: sqlite3.Connection, tmp_path: Path, checks: bool, historical: bool,
) -> None:
    cause = ChecksCause(reason=ChecksReason.COMMIT_MISSING, explanation="Saved <check> context") if checks else DispositionCause(
        reason=DispositionReason.NEEDS_OWNER, explanation="Saved <agent> decision")
    snapshot = event(cause, "implement", "checks" if checks else None, Step.IMPLEMENT)
    checking.execute("UPDATE attempt SET label='auto'")
    if not checks:
        checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
        checking.execute("DELETE FROM checks_attempt")
    HoldStore(lambda: checking).insert(HoldInsert(event=snapshot, now=7))
    if historical:
        checking.execute("UPDATE task_hold SET labels='superseded',labelled_at=8,cleared_at=8")
        checking.execute("UPDATE slot_release SET claim='unclaimed'")
    before = checking.total_changes
    found = detail(checking, tmp_path)
    selected, = (row for row in found.attempts if row.context is not None)
    assert selected.step == ("checks" if checks else "implement") and selected.n == 1
    assert selected.context is not None and selected.context.event == snapshot
    assert selected.context.held_at == "1970-01-01T00:00:07Z" and selected.past == historical
    payload = json.loads(_json(found).body)
    stored, = (row["context"] for row in payload["attempts"] if row["context"] is not None)
    assert stored["event"] == snapshot.model_dump(mode="json")
    assert checking.total_changes == before


def test_absent_snapshot_is_not_inferred_from_current_task_text(checking: sqlite3.Connection, tmp_path: Path) -> None:
    before = checking.total_changes
    assert all(row.context is None for row in detail(checking, tmp_path).attempts)
    assert checking.total_changes == before
