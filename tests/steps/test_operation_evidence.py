"""Operation evidence persists retries and incomplete observations without owning effects."""

import math
from functools import partial
from pathlib import Path

import pytest

from taskloop import operation_file
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.operation_evidence import OperationKind, OperationObserver, OperationSample, OperationState, measured

KEY = AttemptKey("attempt", "dispatch", 1)


def test_retries_and_interruption_survive_reopening_without_counting_downtime(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    now, wall = [10.0], [100.0]
    timing = partial(files.observe_operation, clock=lambda: now[0], wall=lambda: wall[0], ids=NativeIds())
    with measured(timing, KEY, OperationKind.COMMIT) as observed:
        assert files.operations(KEY)[0].state is OperationState.ACTIVE
        now[0] += 4
        wall[0] -= 50
        observed.state = OperationState.FAILED
    with measured(timing, KEY, OperationKind.COMMIT) as observed:
        now[0] += 3
        observed.state = OperationState.COMPLETED
    with pytest.raises(KeyboardInterrupt), measured(timing, KEY, OperationKind.CHECKS_START):
        now[0] += 2
        raise KeyboardInterrupt
    saved = files.operations(KEY)
    assert len({sample.operation for sample in saved}) == 3
    assert {(sample.state, sample.elapsed) for sample in saved} == {
        (OperationState.FAILED, 4.0),
        (OperationState.COMPLETED, 3.0),
        (OperationState.ACTIVE, 0.0),
    }
    now[0] += 9000
    assert EvidenceFiles(tmp_path).operations(KEY) == saved
    for sample in saved:
        if sample.state is OperationState.ACTIVE:
            continue
        files.write_operation(KEY, sample)
        with pytest.raises(ValueError, match="Conflicting final"):
            files.write_operation(KEY, sample.model_copy(update={"elapsed": 90.0}))


def test_missing_read_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    assert EvidenceFiles(root).operations(KEY) == ()
    assert not root.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"elapsed": math.nan},
        {"elapsed": math.inf},
        {"elapsed": -1.0},
        {"started_at": math.nan},
        {"started_at": math.inf},
        {"attempt": ""},
        {"operation": "../escape"},
        {"elapsed": "1"},
    ],
)
def test_invalid_records_cannot_be_written(tmp_path: Path, change: dict[str, object]) -> None:
    files = EvidenceFiles(tmp_path)
    sample = OperationSample(
        operation="a" * 32,
        attempt=files.directory(KEY),
        kind=OperationKind.PUBLISH,
        started_at=1.0,
        elapsed=0.0,
        state=OperationState.ACTIVE,
    )
    with pytest.raises(ValueError):
        files.write_operation(KEY, sample.model_copy(update=change))
    assert not (tmp_path / "attempts").exists()


@pytest.mark.parametrize("data", [b"null", b"{", b"{}", b"x" * (operation_file.CAP + 1)])
@pytest.mark.parametrize("name", [operation_file.ACTIVE, operation_file.FINAL])
def test_corrupt_files_are_unavailable(tmp_path: Path, data: bytes, name: str) -> None:
    files = EvidenceFiles(tmp_path)
    directory = tmp_path / files.directory(KEY) / operation_file.OPERATIONS / ("a" * 32)
    directory.mkdir(parents=True)
    (directory / name).write_bytes(data)
    assert files.operations(KEY) == ()
    assert (directory / name).read_bytes() == data


def test_identity_mismatch_is_rejected_by_writer_and_reader(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    observer = files.observe_operation(KEY, OperationKind.PUBLISH, clock=lambda: 1.0, wall=lambda: 2.0, ids=NativeIds())
    observer.finish(OperationState.COMPLETED)
    (sample,) = files.operations(KEY)
    wrong = sample.model_copy(update={"attempt": "other"})
    with pytest.raises(ValueError, match="identity mismatch"):
        files.write_operation(KEY, wrong)
    directory = tmp_path / files.directory(KEY) / operation_file.OPERATIONS / sample.operation
    (directory / operation_file.FINAL).write_text(wrong.model_dump_json())
    assert files.operations(KEY) == ()


@pytest.mark.parametrize("failure", ["allocation", "wall", "origin", "active", "finish", "backward"])
def test_observation_failure_preserves_one_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    files, ids, now = EvidenceFiles(tmp_path), NativeIds(), [1.0]

    def broken(*_args: object) -> float:
        raise OSError("Evidence unavailable")

    if failure == "allocation":
        monkeypatch.setattr(ids, "hex", broken)
    if failure == "active":
        monkeypatch.setattr(files, "write_operation", broken)
    timing = partial(
        files.observe_operation,
        clock=broken if failure == "origin" else lambda: now[0],
        wall=broken if failure == "wall" else lambda: 100.0,
        ids=ids,
    )
    effects = []
    with measured(timing, KEY, OperationKind.PUBLISH) as observed:
        effects.append("push")
        if failure == "finish":
            monkeypatch.setattr(files, "write_operation", broken)
        now[0] = 0.0 if failure == "backward" else 3.0
        observed.state = OperationState.COMPLETED
    assert effects == ["push"]
    assert all(sample.state is OperationState.ACTIVE for sample in files.operations(KEY))


def test_unknown_exception_is_uncertain_and_preserved(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    timing = partial(files.observe_operation, clock=lambda: 1.0, wall=lambda: 2.0, ids=NativeIds())
    with pytest.raises(OSError), measured(timing, KEY, OperationKind.PUBLISH):
        raise OSError("Push outcome unavailable")
    (sample,) = files.operations(KEY)
    assert sample.state is OperationState.UNCERTAIN


def test_observer_construction_failure_does_not_suppress_or_repeat_effect() -> None:
    def unavailable(_key: AttemptKey, _kind: OperationKind) -> OperationObserver:
        raise OSError("Artifact root unavailable")

    calls = []
    with measured(unavailable, KEY, OperationKind.COMMIT) as observed:
        calls.append(True)
        observed.state = OperationState.COMPLETED
    assert calls == [True]
