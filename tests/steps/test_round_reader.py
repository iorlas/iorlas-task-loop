"""The round log read back for a person (the dashboard): rows from lines the writer produced, a bounded tail, and garbage
skipped. Display only; nothing here is control state."""

from pathlib import Path

import pytest

from taskloop.evidence_files import TAIL_CAP, EvidenceFiles
from taskloop.operations import Move
from taskloop.round_log import stamped
from taskloop.round_reader import LogRow, parse_round_line, read_round_log
from taskloop.round_trail import Trail

ATTEMPT = "0123456789abcdef0123456789abcdef"
AT = "1970-01-01T00:00:10Z"


def written(*moves: Move, stopped: str = "") -> list[str]:
    lines: list[str] = []
    trail = Trail(lines.append, lambda: 10.0, "main", None)
    for move in moves:
        trail.add(move)
    trail.close(stopped)
    return lines


def test_a_task_line_splits_into_step_move_words_and_attempt() -> None:
    lines = written(Move("tl-1", "verify", "verified kept", ATTEMPT, step="implement"), Move("tl-2", "skip", "blocked"))
    assert [parse_round_line(each) for each in lines] == [
        LogRow(AT, "main", "tl-1", "implement", "verify", ("verified", "kept"), ATTEMPT),
        LogRow(AT, "main", "tl-2", None, "skip", ("blocked",), None),
        LogRow(AT, "main", None, None, "round", ("moves=2",), None),
    ]


def test_round_rounds_and_taskless_lines_keep_no_task() -> None:
    assert parse_round_line(stamped(10.0, "main", "round", "moves=0", "stopped=no_free_slot")) == LogRow(
        AT, "main", None, None, "round", ("moves=0", "stopped=no_free_slot"), None
    )
    assert parse_round_line(stamped(10.0, "main", "rounds", "started", "every=30", "pid=7")) == LogRow(
        AT, "main", None, None, "rounds", ("started", "every=30", "pid=7"), None
    )
    (report,) = written(Move("tl-1", "report", "unusable:slot-1:dirty"))[:1]
    assert parse_round_line(report) == LogRow(AT, "main", "tl-1", None, "report", ("unusable:slot-1:dirty",), None)
    assert parse_round_line(stamped(10.0, "main", "no_free_slot")) == LogRow(AT, "main", None, None, "no_free_slot", (), None)


@pytest.mark.parametrize("line", ["", "garbage", "not-a-time main round", "1970-01-01T00:00:10Z", "1970-01-01T00:00:10Z main",
                                  "1970-01-01T00:00:10Z bad/\x00 round x", "1970-01-01T00:00:10Z  main round", "é � �"])
def test_garbage_is_no_row(line: str) -> None:
    assert parse_round_line(line) is None


def test_a_missing_log_reads_empty_and_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    assert EvidenceFiles(root).round_tail(5) == ()
    assert read_round_log(EvidenceFiles(root)) == ()
    assert not root.exists()


def test_the_tail_keeps_the_last_lines_and_reads_only_the_end(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    for number in range(5):
        files.log_round(stamped(float(number), "main", "rounds", "wait", f"seconds={number}"))
    assert [row.words for row in read_round_log(files, 2)] == [("wait", "seconds=3"), ("wait", "seconds=4")]
    assert files.round_tail(0) == ()
    big = "x" * 1000
    files.round_log().write_text("".join(f"{big}{n}\n" for n in range(400)) + stamped(10.0, "main", "round", "moves=0") + "\n")
    tail = files.round_tail(1000)
    assert len(tail) < 400 and tail[-1].endswith("moves=0") and tail[0].startswith(big)


def test_a_partial_first_line_and_bad_bytes_are_skipped(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    cut = "z" * 100
    last = stamped(10.0, "main", "round", "moves=1").encode()
    files.round_log().write_bytes((cut * (TAIL_CAP // 100) + "\n").encode() + b"\xff\xfe junk\n" + last + b"\n")
    rows = read_round_log(files)
    assert [row.move for row in rows] == ["round"]
    tail = files.round_tail(5)
    assert len(tail) == 2 and "junk" in tail[0] and tail[1].endswith("moves=1")
