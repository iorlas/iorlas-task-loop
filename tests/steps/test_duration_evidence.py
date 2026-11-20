"""Duration evidence survives reopening, rejects invalid samples and never owns execution outcomes."""

from pathlib import Path

import pytest
from any_agent import events
from pydantic import ValidationError

from taskloop import duration_file
from taskloop.attempt_types import AttemptKey
from taskloop.command_sink import CommandSink
from taskloop.duration_evidence import DurationSample, DurationState
from taskloop.evidence_files import EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)


def test_reopening_preserves_samples_and_seal_without_counting_downtime(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    now = [1000.0]
    observer = files.observe_duration(KEY, lambda: now[0])
    now[0] += 4
    observer.sample(command=True)
    saved = EvidenceFiles(tmp_path).duration(KEY)
    assert saved is not None and saved.state is DurationState.ACTIVE
    assert saved.elapsed == 4 and saved.command_offset == 4 and saved.number == 1
    now[0] += 3
    observer.seal()
    sealed = EvidenceFiles(tmp_path).duration(KEY)
    assert sealed is not None and sealed.state is DurationState.SEALED
    assert sealed.elapsed == 7 and sealed.command_offset == 4 and sealed.number == 2
    now[0] += 9000
    observer.sample(command=True)
    observer.seal()
    files.write_duration(KEY, sealed)  # identical sealing is idempotent
    assert EvidenceFiles(tmp_path).duration(KEY) == sealed
    for conflicting in [saved, sealed.model_copy(update={"elapsed": 8.0, "number": 3})]:
        with pytest.raises(ValueError, match="Conflicting sealed"):
            files.write_duration(KEY, conflicting)
    assert EvidenceFiles(tmp_path).duration(KEY) == sealed


def test_missing_evidence_read_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    assert EvidenceFiles(root).duration(KEY) is None
    assert not root.exists()


@pytest.mark.parametrize("elapsed", [0.0, 4.0])
def test_restarted_observer_cannot_join_a_saved_active_monotonic_origin(tmp_path: Path, elapsed: float) -> None:
    files = EvidenceFiles(tmp_path)
    now = [1000.0]
    original = files.observe_duration(KEY, lambda: now[0])
    if elapsed:
        now[0] += elapsed
        original.sample(command=True)
    saved = files.duration(KEY)
    restarted = EvidenceFiles(tmp_path).observe_duration(KEY, lambda: now[0])
    for _ in range(10):
        now[0] += 1000
        restarted.sample(command=True)
    restarted.seal()
    assert files.duration(KEY) == saved


@pytest.mark.parametrize("data", [
    b"null", b"{", b"{}", b"x" * (duration_file.CAP + 1),
    b'{"execution":"wrong","elapsed":1,"number":1,"state":"active"}',
    b'{"execution":"wrong","elapsed":NaN,"number":1,"state":"active"}',
])
@pytest.mark.parametrize("name", [duration_file.ACTIVE, duration_file.SEALED])
def test_invalid_files_are_unavailable_without_read_side_effects(tmp_path: Path, data: bytes, name: str) -> None:
    files = EvidenceFiles(tmp_path)
    directory = tmp_path / files.directory(KEY)
    directory.mkdir(parents=True)
    path = directory / name
    path.write_bytes(data)
    before = sorted(directory.iterdir())
    assert files.duration(KEY) is None
    assert path.read_bytes() == data and sorted(directory.iterdir()) == before


@pytest.mark.parametrize("field,value", [
    ("elapsed", -1.0), ("elapsed", float("nan")), ("elapsed", float("inf")),
    ("command_offset", -1.0), ("command_offset", float("inf")), ("command_offset", 5.0),
    ("number", -1), ("number", 1.5), ("extra", 1),
])
def test_sample_validation_rejects_invalid_values(field: str, value: float, tmp_path: Path) -> None:
    fields = {"execution": EvidenceFiles(tmp_path).directory(KEY), "elapsed": 4.0, "number": 1, "state": DurationState.ACTIVE}
    fields[field] = value
    with pytest.raises(ValidationError):
        DurationSample.model_validate(fields)


@pytest.mark.parametrize("change", [
    {"number": 0}, {"elapsed": 3.0}, {"command_offset": None}, {"command_offset": 2.0}, {"execution": "different"},
])
def test_writer_rejects_regression_and_identity_mismatch(tmp_path: Path, change: dict[str, object]) -> None:
    files = EvidenceFiles(tmp_path)
    observer = files.observe_duration(KEY, lambda: 1.0)
    # Drive a sample through the real writer, independently of observer validation.
    saved = DurationSample(execution=files.directory(KEY), elapsed=4.0, command_offset=4.0, number=1, state=DurationState.ACTIVE)
    files.write_duration(KEY, saved)
    changed = saved.model_copy(update={"number": 2, **change})
    with pytest.raises(ValueError):
        files.write_duration(KEY, changed)
    assert files.duration(KEY) == saved
    observer.seal()  # a conflicting older observer cannot erase the saved sample
    assert files.duration(KEY) == saved


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf")])
def test_invalid_clock_invalidates_previous_evidence_and_cannot_later_seal(tmp_path: Path, invalid: float) -> None:
    files = EvidenceFiles(tmp_path)
    now = [1000.0]
    observer = files.observe_duration(KEY, lambda: now[0])
    now[0] += 4
    observer.sample(command=True)
    assert files.duration(KEY) is not None
    now[0] = 1000 + invalid
    observer.sample()
    now[0] = 1010
    observer.seal()
    assert EvidenceFiles(tmp_path).duration(KEY) is None


def test_clock_exceptions_and_unavailable_destination_are_contained(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)

    def broken() -> float:
        raise RuntimeError("clock unavailable")

    observer = files.observe_duration(KEY, broken)
    observer.sample()
    observer.seal()
    assert files.duration(KEY) is None
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    unavailable = EvidenceFiles(blocked).observe_duration(KEY, lambda: 1.0)
    unavailable.sample(command=True)
    unavailable.seal()
    assert EvidenceFiles(blocked).duration(KEY) is None


def test_unreadable_or_corrupt_seal_never_falls_back_to_active_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    observer = files.observe_duration(KEY, lambda: 1000.0)
    observer.seal()
    sealed = tmp_path / files.directory(KEY) / duration_file.SEALED
    original_open = Path.open

    def unreadable(path: Path, mode: str = "r") -> object:
        if path == sealed:
            raise OSError("seal unreadable")
        return original_open(path, mode)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", unreadable)
        assert EvidenceFiles(tmp_path).duration(KEY) is None
    sealed.write_text("null")
    assert files.duration(KEY) is None
    assert (sealed.parent / duration_file.ACTIVE).exists()


@pytest.mark.parametrize("seal", [False, True])
def test_interrupted_publication_preserves_previous_complete_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seal: bool,
) -> None:
    files = EvidenceFiles(tmp_path)
    now = [1000.0]
    observer = files.observe_duration(KEY, lambda: now[0])
    previous = files.duration(KEY)

    def interrupted(_source: Path, _destination: Path) -> None:
        raise OSError("interrupted publication")

    with monkeypatch.context() as patch:
        patch.setattr(duration_file.os, "link" if seal else "replace", interrupted)
        now[0] += 3
        observer.sample(seal=seal)
    assert EvidenceFiles(tmp_path).duration(KEY) == previous
    assert sorted(path.name for path in (tmp_path / files.directory(KEY)).iterdir()) == [duration_file.ACTIVE]


def test_duration_is_independent_of_activity_and_clock_evidence_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    now, wall = [10.0], [1000.0]
    observer = files.observe_duration(KEY, lambda: now[0])

    def lost_clock_evidence() -> None:
        raise OSError("clock evidence lost")

    def lost_activity(_files: EvidenceFiles, _key: AttemptKey) -> None:
        raise OSError("activity lost")

    monkeypatch.setattr(EvidenceFiles, "open_events", lost_activity)
    sink = CommandSink(files, KEY, lambda: wall[0], lost_clock_evidence, observer)
    sink.started(1)
    now[0], wall[0] = 12, 9000
    sink.feed(events.Cmd(id="c1", text="just check"))
    now[0], wall[0] = 13, -9000
    sink.feed(events.CmdEnd(id="c1", text="just check", exit=0))
    now[0] = 14
    sink.feed(events.Msg(text="done"))
    now[0] = 15
    sink.poll(1)
    sink.end("done")
    observer.seal()
    sample = EvidenceFiles(tmp_path).duration(KEY)
    assert sample is not None and sample.elapsed == 5 and sample.command_offset == 2
    assert sample.state is DurationState.SEALED
