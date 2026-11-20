"""Operation timing is read-only evidence attached to the existing attempt chain."""

import sqlite3
from pathlib import Path

import pytest
from dash_read_support import KEY, Tracker, reads_of
from doubles import CHECKS, REQUIRED, TARGET, D
from test_dash_read_restarts import restarted_at_plan, unsafe_repeat

from taskloop.attempt_types import AttemptKey
from taskloop.check_store import ChecksAdmitted, insert
from taskloop.dash_model import TaskDetail
from taskloop.dash_operation import project
from taskloop.dash_task import TaskPorts, build_task
from taskloop.evidence_files import EvidenceFiles
from taskloop.operation_evidence import OperationKind, OperationSample, OperationState


def sample(
    identity: str = "attempt",
    operation: str = "a" * 32,
    *,
    started: float = 100.0,
    kind: OperationKind = OperationKind.COMMIT,
    state: OperationState = OperationState.COMPLETED,
    elapsed: float = 1.25,
) -> OperationSample:
    return OperationSample(operation=operation, attempt=identity, kind=kind, started_at=started, elapsed=elapsed, state=state)


class ReadFiles(EvidenceFiles):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.reads: list[AttemptKey] = []

    def operations(self, key: AttemptKey) -> tuple[OperationSample, ...]:
        self.reads.append(key)
        return super().operations(key)


def save(
    files: EvidenceFiles,
    key: AttemptKey,
    operation: str = "a" * 32,
    *,
    started: float = 100.0,
    kind: OperationKind = OperationKind.COMMIT,
    state: OperationState = OperationState.COMPLETED,
) -> None:
    observed = sample(files.directory(key), operation, started=started, kind=kind, state=OperationState.ACTIVE, elapsed=0.0)
    files.write_operation(key, observed)
    if state is not OperationState.ACTIVE:
        files.write_operation(key, sample(files.directory(key), operation, started=started, kind=kind, state=state))


def detail(con: sqlite3.Connection, files: EvidenceFiles, now: float = 1000.0) -> TaskDetail:
    before = con.total_changes
    found = build_task(TaskPorts(reads_of(con, now), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert con.total_changes == before
    return found


@pytest.mark.parametrize("state", list(OperationState))
def test_saved_measurements_and_incomplete_evidence(state: OperationState) -> None:
    (found,) = project((sample(state=state),), "plan", 2, past=True)
    assert (found.step, found.n, found.past, found.state) == ("plan", 2, True, state)
    assert found.started_at == "1970-01-01T00:01:40.000+00:00"
    assert found.elapsed_ms == (None if state is OperationState.ACTIVE else 1250)
    assert found.model_dump(mode="json")["state"] == state.value


def test_invalid_timestamps_omit_only_affected_samples_and_retries_sort_stably() -> None:
    samples = (
        sample(operation="c" * 32),
        sample(operation="b" * 32, started=99.0),
        sample(operation="a" * 32),
        sample(operation="d" * 32, started=1e100),
    )
    found = project(samples, "implement", 1, past=False)
    assert [each.operation for each in found] == ["b" * 32, "a" * 32, "c" * 32]
    assert project((), "plan", 1, past=False) == ()


def test_checks_and_factory_commit_keep_their_existing_owners_and_read_once(checking: sqlite3.Connection, tmp_path: Path) -> None:
    unsafe_repeat(checking)
    second_checks = AttemptKey("checks-again", "checks-again-token", 1)
    checking.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5 WHERE attempt_id='checks'")
    insert(checking, ChecksAdmitted(second_checks, "implement", 2, "s2", D, TARGET, REQUIRED, 100.0))
    files = ReadFiles(tmp_path)
    baseline = detail(checking, files)
    files.reads.clear()
    implement = AttemptKey("implement", "implement-token", 1)
    again = AttemptKey("again", "again-token", 2)
    save(files, implement, "b" * 32, started=200.0, state=OperationState.FAILED)
    save(files, implement, "c" * 32, started=201.0, kind=OperationKind.PUBLISH)
    save(files, CHECKS, "d" * 32, started=50.0, kind=OperationKind.CHECKS_START, state=OperationState.ACTIVE)
    save(files, second_checks, "f" * 32, started=49.0, kind=OperationKind.CHECKS_START, state=OperationState.FAILED)
    save(files, again, "e" * 32, started=1.0)
    found = detail(checking, files)
    assert files.reads == [implement, CHECKS, second_checks, again]
    assert [(each.step, each.n, each.past) for each in found.operations] == [
        ("implement", 1, False),
        ("implement", 1, False),
        ("checks", 1, False),
        ("checks", 2, False),
        ("implement", 2, False),
    ]
    assert found.attempts == baseline.attempts and found.usage == baseline.usage and found.step_usage == baseline.step_usage
    assert found.operations == detail(checking, EvidenceFiles(tmp_path), 100000.0).operations
    checking.execute("INSERT INTO slot_release VALUES ('again','again-token',2,?,10,'not_held')", (D,))
    assert all(each.past for each in detail(checking, files).operations)


def test_restart_numbering_and_missing_or_corrupt_observations(registered: sqlite3.Connection, tmp_path: Path) -> None:
    restarted_at_plan(registered)
    registered.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,10,'not_held')", (D,))
    files = EvidenceFiles(tmp_path)
    assert detail(registered, files).operations == ()
    save(files, KEY)
    again = AttemptKey("again", "again-token", 1)
    save(files, again, "b" * 32, kind=OperationKind.PUBLISH, state=OperationState.UNCERTAIN)
    save(files, again, "c" * 32)
    broken = tmp_path / files.directory(again) / "operations" / ("c" * 32) / "final.json"
    broken.write_text("{invalid")
    found = detail(registered, files)
    assert [(each.step, each.n, each.past, each.state) for each in found.operations] == [
        ("plan", 1, True, OperationState.COMPLETED),
        ("plan", 2, False, OperationState.UNCERTAIN),
    ]
