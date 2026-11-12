"""Last-command timestamps come only from bounded, complete activity records, without changing evidence on read."""

import io
from pathlib import Path

import pytest
from any_agent.activity import Activity, encode

from taskloop import activity_file, evidence_files
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EVENTS_CAP, TRUNCATED, EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)


def command(at: float) -> bytes:
    return (encode(Activity(kind="command", state="running", at=at, text="pwd", id="c")) + "\n").encode()


def message(text: str = "thinking") -> bytes:
    return (encode(Activity(kind="message", state="finished", at=2000.0, text=text)) + "\n").encode()


def write(files: EvidenceFiles, data: bytes) -> Path:
    path = files.events_path(KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_missing_and_empty_streams_have_no_command_and_reading_makes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    files = EvidenceFiles(root)
    assert files.last_command(KEY) == "none"
    assert not root.exists()
    path = write(files, b"")
    assert files.last_command(KEY) == "none"
    assert path.read_bytes() == b""


def test_a_command_behind_more_than_a_dashboard_page_is_still_found(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    later = message("m" * 1990) * 150
    assert len(later) > activity_file.READ_CAP
    write(files, command(1000.25) + later)
    assert all(record.kind == "message" for record in files.activity_tail(KEY, 10).events)
    assert files.last_command(KEY) == 1000.25


def test_a_command_crossing_the_reverse_chunk_boundary_is_read_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_file, "READ_CAP", 256)
    files = EvidenceFiles(tmp_path)
    latest, later = command(1000.5), message("m" * 160)
    assert len(later) < 256 < len(latest + later)
    write(files, command(1000.0) + latest + later)
    assert files.last_command(KEY) == 1000.5


def test_an_incomplete_final_record_waits_for_its_newline(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    prefix, latest = command(1000.0), command(1001.0)
    path = write(files, prefix + latest[:-1])
    assert files.last_command(KEY) == 1000.0
    assert path.read_bytes() == prefix + latest[:-1]
    with path.open("ab") as stream:
        stream.write(b"\n")
    assert files.last_command(KEY) == 1001.0


@pytest.mark.parametrize("suffix", [b"{\"k\":", b"\xff\xfe", b"unfinished", b"{\"at\":NaN"])
def test_an_incomplete_suffix_does_not_make_earlier_complete_records_unreadable(tmp_path: Path, suffix: bytes) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + suffix)
    assert files.last_command(KEY) == 1000.0


@pytest.mark.parametrize("data", [b"{\"k\":", b"\xff\xfe", b"unfinished"])
def test_a_stream_with_only_an_incomplete_record_has_no_command(tmp_path: Path, data: bytes) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, data)
    assert files.last_command(KEY) == "none"


@pytest.mark.parametrize("bad", [b"not JSON\n", b"\n", b"[]\n", b"{}\n", b"\xff\xfe\n",
                                b'{"k":"message","s":"finished","at":1,"t":"\xff"}\n'])
def test_a_bad_complete_record_after_a_command_makes_the_evidence_unreadable(tmp_path: Path, bad: bytes) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + bad + message())
    assert files.last_command(KEY) == "unreadable"


@pytest.mark.parametrize("at", ["null", '"1001"', "true", "NaN", "Infinity", "-Infinity", "9" * 400])
def test_invalid_command_timestamps_are_unreadable(tmp_path: Path, at: str) -> None:
    files = EvidenceFiles(tmp_path)
    invalid = ('{"k":"command","s":"running","at":' + at + ',"t":"pwd"}\n').encode()
    write(files, command(1000.0) + invalid)
    assert files.last_command(KEY) == "unreadable"


@pytest.mark.parametrize("record", [b'"k":"unknown","s":"running","at":1,"t":"x"', b'"k":"command","s":"unknown","at":1,"t":"x"',
                                     b'"k":"command","s":"running","at":1,"t":null'])
def test_other_invalid_activity_fields_cannot_conceal_a_newer_start(tmp_path: Path, record: bytes) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + b"{" + record + b"}\n")
    assert files.last_command(KEY) == "unreadable"


def test_damage_older_than_the_latest_command_does_not_hide_that_command(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, b"bad\n\xff\xfe\n" + command(1000.0) + message())
    assert files.last_command(KEY) == 1000.0


@pytest.mark.parametrize("suffix", [TRUNCATED, b'{"k":"command",' + TRUNCATED, TRUNCATED + b'{"unfinished":'])
def test_a_cap_marker_never_reports_a_stale_command(tmp_path: Path, suffix: bytes) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + suffix)
    assert files.last_command(KEY) == "unreadable"


def test_a_marker_without_its_newline_is_not_an_ordinary_incomplete_append(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + b'{"k":"message",' + TRUNCATED[:-1])
    assert files.last_command(KEY) == "unreadable"


def test_marker_text_inside_a_valid_message_is_not_a_writer_marker(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    write(files, command(1000.0) + message("the log says [truncated]"))
    assert files.last_command(KEY) == 1000.0


@pytest.mark.parametrize("complete", [False, True])
def test_a_line_larger_than_the_read_bound_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, complete: bool) -> None:
    monkeypatch.setattr(activity_file, "READ_CAP", 256)
    files = EvidenceFiles(tmp_path)
    oversized = message("m" * 257)
    write(files, command(1000.0) + (oversized if complete else oversized[:-1]))
    assert files.last_command(KEY) == "unreadable"


def test_an_oversized_file_is_unreadable_even_with_a_valid_command_at_the_end(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    path = write(files, b"")
    with path.open("wb") as stream:
        stream.seek(EVENTS_CAP + len(TRUNCATED))
        stream.write(command(1000.0))
    assert files.last_command(KEY) == "unreadable"


def test_repeated_cap_markers_from_resumed_writers_are_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    prefix = command(1000.0)
    monkeypatch.setattr(evidence_files, "EVENTS_CAP", len(prefix))
    write(files, prefix + TRUNCATED * 2)
    assert files.last_command(KEY) == "unreadable"


def test_legacy_sidecar_is_ignored_preserved_and_not_a_fallback(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    path = files.events_path(KEY)
    path.parent.mkdir(parents=True)
    sidecar = path.with_name("last-command")
    sidecar.write_text("9999.0")
    assert files.last_command(KEY) == "none"
    write(files, command(1000.0))
    assert files.last_command(KEY) == 1000.0
    assert sidecar.read_text() == "9999.0"


def test_a_directory_in_place_of_the_events_file_is_unreadable(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.events_path(KEY).mkdir(parents=True)
    assert files.last_command(KEY) == "unreadable"


def test_reverse_scanning_uses_bounded_reads_through_the_full_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    path = write(files, command(1000.0) + message("m" * 1990) * 150)
    reads: list[int] = []

    class BoundedFile(io.FileIO):
        def read(self, size: int | None = -1, /) -> bytes | None:
            assert size is not None and 0 <= size <= activity_file.READ_CAP
            reads.append(size)
            return super().read(size)

    def open_bounded(path: Path, mode: str = "r") -> BoundedFile:
        return BoundedFile(path, mode)

    monkeypatch.setattr(Path, "open", open_bounded)
    assert files.last_command(KEY) == 1000.0
    assert len(reads) > 1 and sum(reads) <= path.stat().st_size + len(TRUNCATED)


def test_an_append_during_the_scan_is_observed_on_the_next_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    path = write(files, command(1000.0) + message())
    appended: list[bool] = []

    class AppendingFile(io.FileIO):
        def read(self, size: int | None = -1, /) -> bytes | None:
            if not appended:
                with io.FileIO(path, "ab") as stream:
                    stream.write(command(1001.0))
                appended.append(True)
            return super().read(size)

    def open_appending(path: Path, mode: str = "r") -> AppendingFile:
        return AppendingFile(path, mode)

    monkeypatch.setattr(Path, "open", open_appending)
    assert files.last_command(KEY) == 1000.0
    assert files.last_command(KEY) == 1001.0
