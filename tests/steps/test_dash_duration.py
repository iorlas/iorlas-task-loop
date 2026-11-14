"""Dashboard durations use only evidence for the represented execution, across polls and restarts."""

import sqlite3
from pathlib import Path

import pytest
from test_dash_read import KEY, Tracker, reads_of, saved_ask
from test_recovery_store import OWNER, database, observed

from taskloop import duration_file
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_duration import Duration, project
from taskloop.dash_model import Board, FeedPage, TaskDetail
from taskloop.dash_task import TaskPorts, build_feed, build_task
from taskloop.duration_evidence import DurationSample, DurationState
from taskloop.evidence_files import EvidenceFiles
from taskloop.recovery.store import RecoveryStore


def projections(con: sqlite3.Connection, root: Path, now: float) -> tuple[Duration | None, ...]:
    files, tracker, reads = EvidenceFiles(root), Tracker(), reads_of(con, now)
    before = con.total_changes
    board = build_board(BoardPorts(reads, files, tracker))
    task = build_task(TaskPorts(reads, files, tracker), "tasks", "tl-1")
    feed = build_feed(TaskPorts(reads, files, tracker), "tasks", "tl-1", "plan", 1, None)
    assert isinstance(board, Board) and isinstance(task, TaskDetail) and isinstance(feed, FeedPage)
    assert con.total_changes == before
    attempt = next(each for each in task.attempts if each.step == "plan")
    return board.tasks[0].duration, task.task.duration, attempt.duration, feed.duration


@pytest.mark.parametrize("offset,quiet", [(None, 12500), (3.25, 9250)])
def test_projection_uses_saved_elapsed_and_command_offset(offset: float | None, quiet: int) -> None:
    sample = DurationSample(execution="execution", number=7, elapsed=12.5, command_offset=offset, state=DurationState.ACTIVE)
    found = project(sample, terminal=False)
    assert found is not None
    assert found == Duration(execution="execution", number=7, elapsed_ms=12500, quiet_ms=quiet, frozen=False)
    assert project(sample, terminal=True) is None
    sealed = project(sample.model_copy(update={"state": DurationState.SEALED}), terminal=False)
    assert sealed == found.model_copy(update={"quiet_ms": None, "frozen": True})


@pytest.mark.parametrize("seconds,expected", [(0.0, 0), (12.501, 12501), (1e308, int(1e308) * 1000)])
def test_fractional_and_large_finite_samples_remain_readable(seconds: float, expected: int) -> None:
    sample = DurationSample(execution="execution", number=0, elapsed=seconds, state=DurationState.ACTIVE)
    found = project(sample, terminal=False)
    assert found is not None and found.elapsed_ms == found.quiet_ms == expected


def test_all_reads_agree_across_wall_jumps_and_reopened_database_and_files(tmp_path: Path) -> None:
    path, root = tmp_path / "factory.db", tmp_path / "evidence"
    con = database(path)
    files = EvidenceFiles(root)
    monotonic = [10.0]
    observer = files.observe_duration(KEY, lambda: monotonic[0])
    monotonic[0] = 13.0
    observer.sample(command=True)
    monotonic[0] = 22.5
    observer.sample()
    expected = projections(con, root, 10)[0]
    assert expected is not None and (expected.elapsed_ms, expected.quiet_ms, expected.frozen) == (12500, 9500, False)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    for wall in (1000000000, 1, 2000000000):
        con.close()
        con = sqlite3.connect(path, isolation_level=None)
        assert projections(con, root, wall) == (expected,) * 4
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    con.close()


def test_continuation_selects_only_its_own_saved_evidence(tmp_path: Path) -> None:
    path, root = tmp_path / "factory.db", tmp_path / "evidence"
    con = database(path)
    files = EvidenceFiles(root)
    files.observe_duration(KEY, lambda: 0.0).seal()
    store = RecoveryStore(lambda: con)
    authorized = store.authorize(observed(store), OWNER, "continuation", lambda: 10)
    assert authorized.intent is not None
    assert projections(con, root, 10) == (None,) * 4  # initial evidence cannot fill a missing continuation sample
    clock = iter((10.0, 12.5))
    observer = files.observe_duration(KEY, clock.__next__, authorized.intent)
    observer.sample()
    expected = projections(con, root, 10)[0]
    assert expected is not None and expected.elapsed_ms == expected.quiet_ms == 2500
    assert expected.execution == files.directory(KEY, authorized.intent)
    con.close()
    with sqlite3.connect(path) as reopened:
        assert projections(reopened, root, 1000000) == (expected,) * 4


@pytest.mark.parametrize("sealed", [False, True])
@pytest.mark.parametrize("released", [False, True])
def test_terminal_duration_requires_a_seal_and_freezes_across_restarts(tmp_path: Path, sealed: bool, released: bool) -> None:
    path, root = tmp_path / "factory.db", tmp_path / "evidence"
    con = database(path)
    files = EvidenceFiles(root)
    if released:
        con.execute("DELETE FROM reservation")
        con.execute("INSERT INTO slot_release VALUES ('attempt','dispatch',1,?,12,'unclaimed')", ("d" * 40,))
    else:
        saved_ask(con, files)
    clock = iter((1.0, 8.5))
    observer = files.observe_duration(KEY, clock.__next__)
    observer.sample(seal=sealed)
    expected = projections(con, root, 10)[0]
    if sealed:
        assert expected is not None and (expected.elapsed_ms, expected.quiet_ms, expected.frozen) == (7500, None, True)
    else:
        assert expected is None
    con.close()
    with sqlite3.connect(path) as reopened:
        assert projections(reopened, root, 2000000000) == (expected,) * 4


@pytest.mark.parametrize("data", [None, b"broken", b'{}',
    b'{"execution":"wrong","elapsed":5,"number":1,"state":"active"}',
    b'{"execution":"IDENTITY","elapsed":-1,"number":1,"state":"active"}',
    b'{"execution":"IDENTITY","elapsed":1,"command_offset":2,"number":1,"state":"active"}',
    b'{"execution":"IDENTITY","elapsed":NaN,"number":1,"state":"active"}'])
def test_invalid_evidence_is_unknown_without_mutating_task_data(tmp_path: Path, data: bytes | None) -> None:
    root = tmp_path / "evidence"
    con = database(tmp_path / "factory.db")
    directory = root / EvidenceFiles(root).directory(KEY)
    if data is not None:
        directory.mkdir(parents=True)
        data = data.replace(b"IDENTITY", EvidenceFiles(root).directory(KEY).encode())
        (directory / duration_file.ACTIVE).write_bytes(data)
    assert projections(con, root, 1000000) == (None,) * 4
    if data is not None:
        assert (directory / duration_file.ACTIVE).read_bytes() == data
    else:
        assert not root.exists()
    con.close()


def test_damaged_seal_cannot_fall_back_to_an_active_sample(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    con = database(tmp_path / "factory.db")
    files = EvidenceFiles(root)
    files.observe_duration(KEY, lambda: 0.0)
    seal = root / files.directory(KEY) / duration_file.SEALED
    seal.write_bytes(b"broken")
    assert projections(con, root, 10) == (None,) * 4
    assert seal.read_bytes() == b"broken"
    con.close()
