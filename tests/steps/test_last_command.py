"""The time since the agent's last command in `tl step show` and `tl step list` (roadmap B10): a live sink notes it in the
attempt's evidence while the agent runs, the status reads it back. Display only: it never changes the `Next` word."""

import sqlite3
from pathlib import Path

import pytest
from any_agent import events

from taskloop.attempt_status import Listed, Shown, StatusPorts, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Seen
from taskloop.command_sink import CommandSink
from taskloop.evidence_files import EvidenceFiles
from taskloop.result_data import as_data
from taskloop.step_render import human

KEY = AttemptKey("attempt", "dispatch", 1)


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def command(sink: CommandSink) -> None:
    sink.feed(events.Cmd(id="1", text="just test"))


def seen(con: sqlite3.Connection, files: EvidenceFiles, now: float, entry: Seen = "matching") -> tuple[list[str], list[str], object]:
    """`tl step show`'s lines, `tl step list`'s lines and the listed attempt's JSON `last_command`."""
    reads = StatusPorts(AttemptStore(lambda: con), lambda _entry: entry, lambda: now, lambda _key: None, lambda: "boot",
                        last_command=files.last_command)
    shown, listed = show_attempt(reads, files.root, "tasks", "tl-1"), list_attempts(reads)
    assert isinstance(shown, Shown) and isinstance(listed, Listed)
    rows = as_data(listed)["attempts"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    return human("tl step show", shown, None), human("tl step list", listed, None), rows[0]["last_command"]


def test_a_running_agent_shows_the_seconds_since_its_last_command(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files, clock = EvidenceFiles(tmp_path), Clock(10.0)
    sink = CommandSink(files, KEY, clock)
    command(sink)
    clock.now = 10.4
    command(sink)  # inside the second: not written again
    clock.now = 13.0
    command(sink)
    show, rows, data = seen(registered, files, 20.0)
    assert "Last command: 7 s ago" in show
    assert rows[0].endswith("\tlast command") and rows[1].endswith("\twait\t7 s ago")
    assert data == 7


@pytest.mark.parametrize("evidence", [None, "not a time", ""])
def test_no_or_unreadable_evidence_shows_the_word_unknown(registered: sqlite3.Connection, tmp_path: Path, evidence: str | None) -> None:
    files = EvidenceFiles(tmp_path)
    if evidence is not None:
        files.note_command(KEY, 0.0)
        (tmp_path / files.directory(KEY) / "last-command").write_text(evidence)
    show, rows, data = seen(registered, files, 20.0)
    assert "Last command: unknown" in show and rows[1].endswith("\twait\tunknown")
    assert data == "unknown"


def test_an_agent_that_cannot_be_running_shows_no_time_and_the_next_word_is_unchanged(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.note_command(KEY, 10.0)
    running, gone = seen(registered, files, 20.0), seen(registered, files, 20.0, entry="gone")
    assert not any(line.startswith("Last command") for line in gone[0]) and gone[1][1].endswith("\t-") and gone[2] is None
    assert "Next: wait" in running[0] and "Next: start" in gone[0]


def test_a_failed_write_never_fails_the_run(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    command(CommandSink(EvidenceFiles(blocked), KEY, Clock(1.0)))
