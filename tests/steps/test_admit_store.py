"""Admission's SQL boundary, typed reads and transaction participation through real SQLite."""

import ast
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import ENGINE, PIN_DIGEST, PIN_SHA
from sqlite_sidecar import transaction as begin_immediate

from taskloop import admit_store
from taskloop.admit_rows import Free
from taskloop.attempt_types import AttemptKey
from taskloop.repo import RepoId
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore

REPO = RepoId("repo")
KEY = AttemptKey("attempt", "dispatch", 1)
EVIDENCE = TaskContentDigest(value="d" * 64)
FREE = Free("s1", "a" * 40, "b" * 40, "c" * 40)


def values(key: AttemptKey = KEY) -> dict[str, object]:
    return {
        "attempt_id": key.attempt_id,
        "dispatch_token": key.dispatch_token,
        "generation": key.reservation_generation,
        "step": "plan",
        "adapter": "beads",
        "backlog": "tasks",
        "task_id": "tl-1",
        "tracker_root": "/tracker",
        "repo_id": REPO,
        "slot": "s1",
        "input_path": "input.txt",
        "input_digest": "e" * 64,
        "schema_version": 1,
        "model": "chosen",
        "effort": "high",
        "access_policy": '{"harness":"codex","sandbox":"workspace-write"}',
        "deadline": 100,
        "number": 1,
        "seq": 1,
        "slot_head": FREE.head,
        "previous_attempt_id": None,
        "repeat_reason": None,
        "repeat_listing": None,
        "after_commit": None,
        "label": "approved",
        "harness": "codex",
        "provider": "openai",
        "compaction_token_limit": 12000,
        "engine_digest": ENGINE,
        "declared_start": 0,
        "workflow_digest": PIN_DIGEST,
        "workflow_sha": PIN_SHA,
        "admitted_at": 1.0,
    }


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1','/slots/s1')", (REPO,))
    return factory


@pytest.mark.parametrize("module", ["admit_rows", "admit_chain", "admit"])
def test_admission_modules_do_not_execute_sql(module: str) -> None:
    path = Path(__file__).resolve().parents[2] / "src" / "taskloop" / f"{module}.py"
    tree = ast.parse(path.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "executescript", "cursor"}
    ]
    assert not calls, [(call.lineno, ast.unparse(call)) for call in calls]


def test_admission_reads_and_effects_share_the_callers_transaction(con: sqlite3.Connection) -> None:
    assert admit_store.current(con, "tasks", "tl-1") is None
    assert admit_store.previous(con, KEY) is None and admit_store.task_of(con, KEY) is None
    assert admit_store.issued(con, REPO, ()) == 0
    assert not admit_store.task_attempted(con, "tasks", "tl-1")
    assert admit_store.next_seq(con, "tasks", "tl-1") == 1
    assert admit_store.unheld(con, REPO, FREE, 1) == ("s1", FREE.park_commit)
    with begin_immediate(con):
        admit_store.reserve(con, REPO, "s1", KEY)
        admit_store.insert_attempt(con, values(), EVIDENCE)
        assert con.in_transaction
    row = admit_store.current(con, "tasks", "tl-1")
    assert row is not None and row.key == KEY and not row.done
    assert (row.step, row.end_commit, row.tracker_root, row.seq, row.label) == ("plan", None, "/tracker", 1, "approved")
    prior = admit_store.previous(con, KEY)
    assert prior is not None and not prior.repeated and not prior.repeatable
    assert (prior.model, prior.effort, prior.compaction_token_limit, prior.slot_head) == ("chosen", "high", 12000, FREE.head)
    task = admit_store.task_of(con, KEY)
    assert task is not None and task.current and task.task_id == "tl-1"
    assert admit_store.task_of(con, replace(KEY, dispatch_token="stale")) is None
    assert admit_store.previous(con, replace(KEY, reservation_generation=2)) is None
    assert TaskContentStore(lambda: con).read(KEY.attempt_id) == EVIDENCE
    assert admit_store.issued(con, REPO, ("s1",)) == 1
    assert admit_store.task_attempted(con, "tasks", "tl-1")
    assert admit_store.next_seq(con, "tasks", "tl-1") == 2
    assert admit_store.unheld(con, REPO, FREE, 2) is None


@pytest.mark.parametrize("evidence_fails", [False, True])
def test_admission_failure_rolls_back_reservation_generation_attempt_and_evidence(
    con: sqlite3.Connection,
    evidence_fails: bool,
) -> None:
    if evidence_fails:
        con.execute("CREATE TRIGGER reject_evidence BEFORE INSERT ON task_content BEGIN SELECT RAISE(ABORT,'evidence unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError), begin_immediate(con):
        admit_store.reserve(con, REPO, "s1", KEY)
        admit_store.insert_attempt(con, values(), EVIDENCE if evidence_fails else None)
    assert con.execute("SELECT * FROM reservation").fetchall() == []
    assert con.execute("SELECT * FROM attempt").fetchall() == []
    assert con.execute("SELECT * FROM task_content").fetchall() == []
    assert admit_store.issued(con, REPO, ("s1",)) == 0
    assert admit_store.unheld(con, REPO, FREE, 1) == ("s1", FREE.park_commit)


def test_transfer_fences_the_previous_holder_and_updates_generation_only_when_moved(con: sqlite3.Connection) -> None:
    successor = AttemptKey("successor", "next-dispatch", 2)
    with begin_immediate(con):
        admit_store.reserve(con, REPO, "s1", KEY)
    for stale in (replace(KEY, attempt_id="other"), replace(KEY, reservation_generation=2)):
        with begin_immediate(con):
            assert not admit_store.transfer(con, stale, successor, REPO, "s1")
        assert admit_store.issued(con, REPO, ("s1",)) == 1
    with begin_immediate(con):
        assert admit_store.transfer(con, KEY, successor, REPO, "s1")
    assert con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == ("successor", 2)
    assert admit_store.issued(con, REPO, ("s1",)) == 2


@pytest.mark.parametrize(("column", "value"), [("seq", "malformed"), ("step", "check"), ("step", "review")])
def test_malformed_stored_admission_uses_the_store_error_path(con: sqlite3.Connection, column: str, value: str) -> None:
    with begin_immediate(con):
        admit_store.insert_attempt(con, values(), EVIDENCE)
    con.execute("PRAGMA ignore_check_constraints=ON")
    con.execute(f"UPDATE attempt SET {column}=? WHERE attempt_id=?", (value, KEY.attempt_id))
    with pytest.raises(sqlite3.DatabaseError, match="Malformed admission row"):
        admit_store.current(con, "tasks", "tl-1")
    with pytest.raises(sqlite3.DatabaseError, match="Malformed admission row"):
        admit_store.previous(con, KEY)
    if column == "step":
        with pytest.raises(sqlite3.DatabaseError, match="Malformed admission row"):
            admit_store.task_of(con, KEY)


def test_failed_transfer_allows_the_caller_to_roll_back_the_inserted_successor(con: sqlite3.Connection) -> None:
    with begin_immediate(con):
        admit_store.reserve(con, REPO, "s1", KEY)
        admit_store.insert_attempt(con, values(), EVIDENCE)
    successor = AttemptKey("successor", "next-dispatch", 2)
    repeated = values(successor)
    repeated.update(number=2, seq=2, previous_attempt_id=KEY.attempt_id, repeat_reason="uncommitted")
    stale = replace(KEY, reservation_generation=3)
    with pytest.raises(RuntimeError, match="stale reservation"), begin_immediate(con):
        admit_store.insert_attempt(con, repeated, EVIDENCE)
        if not admit_store.transfer(con, stale, successor, REPO, "s1"):
            raise RuntimeError("stale reservation")
    row = admit_store.current(con, "tasks", "tl-1")
    assert row is not None and row.key == KEY
    assert admit_store.next_seq(con, "tasks", "tl-1") == 2
    assert TaskContentStore(lambda: con).read(successor.attempt_id) is None
    assert con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (KEY.attempt_id, 1)
    assert admit_store.issued(con, REPO, ("s1",)) == 1
