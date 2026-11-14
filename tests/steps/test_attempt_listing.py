"""Current cards hydrate one row per task; explicit history and whole-step addressing survive restarts."""
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import DONE
from doubles import D
from sqlite_store import SchemaError, Store

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_status import Listed, StatusPorts, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Seen
from taskloop.dash_board import BoardPorts, build_board, tries
from taskloop.dash_model import Board, Ready
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.operations import Failed


def add(con: sqlite3.Connection, key: str, seq: int, backlog: str = "tasks", task: str = "tl-1", repo: str = "repo",
        previous: str | None = None, step: str = "plan") -> None:
    con.execute("""INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,
        repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,
        previous_attempt_id,repeat_reason,after_commit)
        SELECT ?,?,1,?,adapter,?,?,tracker_root,?,slot,input_path,input_digest,schema_version,model,effort,access_policy,
        deadline,?,?,slot_head,?,?,? FROM attempt WHERE attempt_id='attempt'""",
        (key, key, step, backlog, task, repo, 2 if previous else 1, seq, previous, "unsafe" if previous else None,
         "a" * 40 if step == "implement" and previous is None else None))


class Tracker:
    def ready(self) -> tuple[Ready, ...]:
        return ()

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {key: key for key in task_ids}

    def fields(self, task_id: str) -> None:
        return None

    def notice(self) -> None:
        return None


class CurrentOnly(AttemptStore):
    def attempts(self, backlog: str | None = None, task_id: str | None = None) -> tuple[()]:
        raise AssertionError("Board must never hydrate history")


def ports(store: AttemptStore) -> StatusPorts:
    return StatusPorts(store, lambda _: "gone", lambda: 200, lambda _: None, lambda: "boot")


def test_scoped_history_and_current_rows_keep_all_identities_and_restart_counts(registered: sqlite3.Connection) -> None:
    add(registered, "repeat", 2, previous="attempt")
    add(registered, "implement", 3, step="implement")
    add(registered, "restart", 4)
    add(registered, "other-backlog", 1, backlog="other", repo="other-repo")
    add(registered, "other-task", 1, task="tl-2")
    store = AttemptStore(lambda: registered)
    all_rows = store.attempts()
    for backlog, task in ((None, None), ("tasks", None), (None, "tl-1"), ("tasks", "tl-1")):
        assert store.attempts(backlog, task) == tuple(row for row in all_rows
            if (backlog is None or row.backlog == backlog) and (task is None or row.task_id == task))
    current = store.current_attempts()
    assert [row.key.attempt_id for row in current] == ["other-backlog", "restart", "other-task"]
    numbers = tries(all_rows)
    assert [row.try_number for row in current] == [numbers[row.key.attempt_id] for row in current] == [1, 3, 1]
    assert [replace(row, try_number=None) for row in current] == [all_rows[0], all_rows[1], all_rows[-1]]
    assert store.attempts("missing") == ()


def test_board_selects_current_once_and_retains_restart_try_addressing(registered: sqlite3.Connection, tmp_path: Path) -> None:
    add(registered, "repeat", 2, previous="attempt")
    add(registered, "restart", 3)
    sql: list[str] = []
    registered.set_trace_callback(sql.append)
    board = build_board(BoardPorts(ports(CurrentOnly(lambda: registered)), EvidenceFiles(tmp_path), Tracker()))
    assert isinstance(board, Board) and len(board.tasks) == 1
    assert board.tasks[0].attempt == 3 and board.tasks[0].repeat is not None
    selections = [query for query in sql if "FROM attempt p" in query and "p.access_policy" in query]
    assert len(selections) == 1 and "max(seq)" in selections[0]
    plan = registered.execute("EXPLAIN QUERY PLAN " + selections[0]).fetchall()
    assert any("COVERING INDEX attempt_step_count" in row[3] for row in plan)


def test_listing_finishes_its_selection_before_external_observation(registered: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: registered)
    def observed(_: object) -> Seen:
        assert not registered.in_transaction
        add(registered, "admitted-during-observation", 2)
        return "gone"
    reads = replace(ports(store), observe=observed)
    listed = list_attempts(reads)
    assert isinstance(listed, Listed) and [row.attempt_id for row in listed.attempts] == ["attempt"]
    assert store.current_attempts()[0].key.attempt_id == "admitted-during-observation"


@pytest.mark.parametrize("metadata", ["slot_names", "slot_use"])
def test_missing_store_and_board_metadata_are_typed_failures(registered: sqlite3.Connection, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch, metadata: str) -> None:
    assert isinstance(list_attempts(ports(AttemptStore(lambda: None))), Failed)
    store = AttemptStore(lambda: registered)
    def unavailable() -> tuple[str, ...]:
        raise StoreUnavailable("unavailable metadata")
    monkeypatch.setattr(store, metadata, unavailable)
    assert build_board(BoardPorts(ports(store), EvidenceFiles(tmp_path), Tracker())) == Failed(
        "unavailable", "store", "unavailable metadata")


def test_scoped_predicates_use_the_task_index(registered: sqlite3.Connection) -> None:
    sql: list[str] = []
    registered.set_trace_callback(sql.append)
    AttemptStore(lambda: registered).attempts("tasks", "tl-1")
    select = next(query for query in sql if "FROM attempt p" in query)
    plan = registered.execute("EXPLAIN QUERY PLAN " + select).fetchall()
    assert any("SEARCH p USING INDEX" in row[3] and "backlog=? AND task_id=?" in row[3] for row in plan)


def test_previous_schema_is_refused_without_changing_the_database(tmp_path: Path) -> None:
    path = tmp_path / "preserved-v20.db"
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA user_version=20")
    con.execute("CREATE TABLE preserved (value TEXT)")
    con.execute("INSERT INTO preserved VALUES ('owner data')")
    con.close()
    before = path.read_bytes()
    with pytest.raises(SchemaError):
        Store(SCHEMA).open_rw(path)
    assert path.read_bytes() == before


def test_slot_lookup_seeks_agent_and_check_keys_without_a_repository_scan(registered: sqlite3.Connection) -> None:
    registered.execute("""INSERT INTO checks_attempt
        (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,required,deadline)
        VALUES ('check','check',1,'attempt',1,'s1',?,?,'[]',100)""", (D, D))
    store = AttemptStore(lambda: registered)
    assert store.slot_path("attempt") == store.slot_path("check")
    assert store.slot_path("absent") is None
    sql: list[str] = []
    registered.set_trace_callback(sql.append)
    store.slot_path("absent")
    query = next(query for query in sql if "UNION ALL" in query)
    details = [row[3] for row in registered.execute("EXPLAIN QUERY PLAN " + query)]
    assert not any(detail.startswith("SCAN p") or detail.startswith("SCAN c") for detail in details)


def test_board_keeps_landed_cards_and_uses_the_checks_number(landing: sqlite3.Connection, tmp_path: Path) -> None:
    landing.execute(DONE[0])
    landing.execute(DONE[1])
    landing.execute("INSERT INTO published_branch VALUES ('implement','implement-token',1,?,?,6)", (D, D))
    landing.execute("""UPDATE land_candidate SET validation='passed',validated_at=5,delivery='pushed',delivered_at=6,
        remote_head=?,close='closed',closed_at=7,released_at=6,parked=?""", (D, D))
    board = build_board(BoardPorts(ports(CurrentOnly(lambda: landing)), EvidenceFiles(tmp_path), Tracker()))
    assert isinstance(board, Board) and len(board.tasks) == 1
    assert (board.tasks[0].column, board.tasks[0].attempt, board.tasks[0].step_started_at) == (
        "landed", 1, "1970-01-01T00:00:07Z")


@pytest.mark.parametrize("finished", [False, True])
def test_board_keeps_finished_and_unfinished_holds(registered: sqlite3.Connection, tmp_path: Path, finished: bool) -> None:
    registered.execute("UPDATE attempt SET label='auto'")
    registered.execute("""INSERT INTO task_hold (attempt_id,cause_id,reason,held_at,labels,labelled_at,commenting_at,commented_at)
        VALUES ('attempt','attempt','needs_owner',1,'moved',2,3,?)""", (4 if finished else None,))
    if finished:
        registered.execute("INSERT INTO slot_release VALUES ('attempt','dispatch',1,?,5,'unclaimed')", (D,))
    board = build_board(BoardPorts(ports(CurrentOnly(lambda: registered)), EvidenceFiles(tmp_path), Tracker()))
    assert isinstance(board, Board) and len(board.tasks) == 1
    assert (board.tasks[0].column, board.tasks[0].hold_cause, board.tasks[0].step_started_at) == (
        "held", "needs_owner", "1970-01-01T00:00:01Z")


def test_admission_during_selection_cannot_mix_the_current_row_and_its_count(registered: sqlite3.Connection, tmp_path: Path) -> None:
    for seq in range(2, 51):
        add(registered, f"history-{seq}", seq)
    path = tmp_path / "concurrent.db"
    reader = Store(SCHEMA).open_rw(path)
    writer = Store(SCHEMA).open_rw(path)
    assert reader is not None and writer is not None
    registered.backup(reader)
    admitted = False
    def admission() -> int:
        nonlocal admitted
        if not admitted:
            admitted = True
            add(writer, "concurrent", 51)
        return 0
    try:
        reader.execute("SELECT count(*) FROM attempt").fetchone()
        reader.set_progress_handler(admission, 500)
        (selected,) = AttemptStore(lambda: reader).current_attempts()
        reader.set_progress_handler(None, 0)
        assert admitted and selected.seq == selected.try_number == 50
        (next_read,) = AttemptStore(lambda: reader).current_attempts()
        assert next_read.seq == next_read.try_number == 51
        assert not reader.in_transaction
    finally:
        writer.close()
        reader.close()


def test_empty_current_listing_and_board_are_successful(factory: sqlite3.Connection, tmp_path: Path) -> None:
    reads = ports(CurrentOnly(lambda: factory))
    assert list_attempts(reads) == Listed(())
    board = build_board(BoardPorts(reads, EvidenceFiles(tmp_path), Tracker()))
    assert isinstance(board, Board) and board.tasks == () and board.slots == ()
