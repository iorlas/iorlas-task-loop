"""Task detail retains the deciding hold snapshot after clearing or abandoning its chain."""

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import checking, factory
from hold_fixtures import event

from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.dash_model import AttemptBody, Comment, Fields, Ready, TaskDetail
from taskloop.dash_server import _json
from taskloop.dash_task import TaskPorts, build_body, build_task
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


def repeat_ports(con: sqlite3.Connection, tmp_path: Path, before: str, now: str) -> TaskPorts:
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,
        repeat_reason,base_commit) SELECT 'again','again-token',2,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,2,3,slot_head,'implement','unsafe',?
        FROM attempt WHERE attempt_id='implement'""", ("c" * 40,))
    files = EvidenceFiles(tmp_path)
    for key, text in ((AttemptKey("implement", "implement-token", 1), before), (AttemptKey("again", "again-token", 2), now)):
        ref = files.put_input(key, text)
        con.execute("UPDATE attempt SET input_path=?,input_digest=? WHERE attempt_id=?", (ref.path, ref.digest, key.attempt_id))
    reads = StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: 10, lambda _key: None, lambda: "boot")
    return TaskPorts(reads, files, Tracker())


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize(("before", "now", "added"), [
    ("Title\nKeep\n", "Title\nAdded <prompt>\nKeep\n", ((1, 2),)),
    ("Title\nOld\nKeep\n", "Title\nNew\nMore\nKeep\n", ((1, 3),)),
    ("Same\n", "Same\n", ()),
    ("Title\nRemoved\n", "Title\n", ()),
])
def test_repeat_changes_use_recorded_bases_and_prompt_ranges_without_writing(
    checking: sqlite3.Connection, tmp_path: Path, historical: bool,
    before: str, now: str, added: tuple[tuple[int, int], ...],
) -> None:
    ports = repeat_ports(checking, tmp_path, before, now)
    if historical:
        checking.execute("INSERT INTO slot_release VALUES ('again','again-token',2,?,8,'unclaimed')", ("d" * 40,))
    changes = checking.total_changes
    first = build_body(ports, "tasks", "tl-1", "implement", 1)
    second = build_body(ports, "tasks", "tl-1", "implement", 2)
    assert isinstance(first, AttemptBody) and first.change is None and first.added == ()
    assert isinstance(second, AttemptBody) and second.input == now and second.added == added
    assert second.change is not None
    assert second.change.base_before == "b" * 40 and second.change.base_after == "c" * 40
    payload = json.loads(_json(second).body)
    assert payload["change"] == {"base_before": "b" * 40, "base_after": "c" * 40}
    assert payload["added"] == [list(pair) for pair in added]
    checks = build_body(ports, "tasks", "tl-1", "checks", 1)
    assert isinstance(checks, AttemptBody) and checks.change is None
    assert checking.total_changes == changes


@pytest.mark.parametrize(("before", "after"), [("b" * 40, "b" * 40), (None, "c" * 40), ("b" * 40, None), (None, None)])
def test_repeat_bases_can_be_unchanged_or_unavailable(
    checking: sqlite3.Connection, tmp_path: Path, before: str | None, after: str | None,
) -> None:
    ports = repeat_ports(checking, tmp_path, "same", "same")
    checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    checking.execute("DELETE FROM checks_attempt")
    checking.execute("UPDATE attempt SET phase='admitted',end_commit=NULL,base_commit=? WHERE attempt_id='implement'", (before,))
    checking.execute("UPDATE attempt SET base_commit=? WHERE attempt_id='again'", (after,))
    found = build_body(ports, "tasks", "tl-1", "implement", 2)
    assert isinstance(found, AttemptBody) and found.change is not None
    assert found.change.base_before == before and found.change.base_after == after and found.added == ()


def test_unlinked_restart_has_no_prompt_or_base_comparison(checking: sqlite3.Connection, tmp_path: Path) -> None:
    ports = repeat_ports(checking, tmp_path, "old", "new")
    checking.execute("UPDATE attempt SET step='plan',number=1,previous_attempt_id=NULL,repeat_reason=NULL WHERE attempt_id='again'")
    found = build_body(ports, "tasks", "tl-1", "plan", 1)
    assert isinstance(found, AttemptBody) and found.change is None and found.added == ()


def test_missing_repeat_prompt_remains_unavailable(checking: sqlite3.Connection, tmp_path: Path) -> None:
    ports = repeat_ports(checking, tmp_path, "old", "new")
    checking.execute("UPDATE attempt SET input_digest='damaged' WHERE attempt_id='implement'")
    reply = _json(build_body(ports, "tasks", "tl-1", "implement", 2))
    assert reply.status == 503 and json.loads(reply.body)["error"]
