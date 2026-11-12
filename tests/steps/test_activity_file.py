"""The agent's activity of one attempt: the live sink writes `events.jsonl`, the evidence reader returns the latest actions and a
cursor to follow, `replaced` on another file and bounded in what it reads. Display only."""

from pathlib import Path

import pytest
from any_agent import events
from any_agent.activity import encode

from taskloop import activity_file
from taskloop.attempt_types import AttemptKey
from taskloop.command_sink import CommandSink
from taskloop.evidence_files import EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)


class Wall:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        self.now += 2.0
        return self.now


def run(files: EvidenceFiles, *items: events.HarnessEvent) -> CommandSink:
    sink = CommandSink(files, KEY, Wall(), Wall())
    for item in items:
        sink.feed(item)
    return sink


def test_a_command_is_one_logical_action_with_its_wait_and_duration(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    run(files, events.Msg(text="looking", final=False), events.Cmd(id="c1", text="ls"), events.CmdEnd(id="c1", text="ls", exit=0))
    page = files.activity_tail(KEY, 10)
    assert [(a.kind, a.state, a.text) for a in page.events] == [("message", "finished", "looking"), ("command", "finished", "ls")]
    assert page.events[1].waited_ms is not None and (page.events[1].duration_ms or 0) > 0 and page.available and not page.replaced


def test_the_tail_is_the_latest_n_and_a_follow_returns_only_what_came_after_it(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    sink = run(files, *(events.Msg(text=f"m{n}") for n in range(30)))
    page = files.activity_tail(KEY, 10)
    assert [a.text for a in page.events] == [f"m{n}" for n in range(20, 30)] and page.cursor is not None
    assert files.activity_after(KEY, page.cursor, 10).events == ()
    sink.feed(events.Cmd(id="c", text="make"))
    more = files.activity_after(KEY, page.cursor, 10)
    assert [(a.text, a.state) for a in more.events] == [("make", "running")] and not more.replaced and more.cursor is not None
    sink.feed(events.CmdEnd(id="c", text="make", exit=1))
    last = files.activity_after(KEY, more.cursor, 10)
    assert [(a.id, a.state, a.exit_code) for a in last.events] == [("c", "finished", 1)]


def test_a_cursor_of_another_file_or_past_its_end_resets_to_the_tail(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    run(files, events.Msg(text="one"), events.Msg(text="two"))
    page = files.activity_tail(KEY, 10)
    assert page.cursor is not None
    for stale in ("garbage", "1:9999999", page.cursor.split(":")[0] + ":99999", "0:0"):
        again = files.activity_after(KEY, stale, 1)
        assert again.replaced and [a.text for a in again.events] == ["two"]


def test_an_attempt_without_events_is_unavailable_not_empty_and_nothing_is_created(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    assert not files.activity_tail(KEY, 10).available and not files.activity_after(KEY, "1:0", 10).available
    assert not (tmp_path / "attempts").exists()


def test_a_half_written_line_waits_and_other_lines_are_skipped(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    run(files, events.Msg(text="whole"))
    path = files.events_path(KEY)
    page = files.activity_tail(KEY, 10)
    half = encode(next(iter(page.events)))
    with path.open("ab") as stream:
        stream.write(b"[truncated]\n" + half[:10].encode())
    again = files.activity_tail(KEY, 10)
    assert [a.text for a in again.events] == ["whole"]
    assert again.cursor is not None and again.cursor.endswith(f":{path.stat().st_size - 10}")  # it stops before the half line
    with path.open("ab") as stream:
        stream.write(half[10:].encode() + b"\n")
    assert [a.text for a in files.activity_after(KEY, again.cursor or "", 10).events] == ["whole"]  # the whole record, once complete


def test_a_big_file_is_read_in_bounded_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_file, "READ_CAP", 2000)
    files = EvidenceFiles(tmp_path)
    run(files, *(events.Msg(text=f"message {n:03}") for n in range(100)))
    page = files.activity_tail(KEY, 1000)
    assert 0 < len(page.events) < 100 and page.events[-1].text == "message 099" and page.cursor is not None
    start = files.activity_after(KEY, "0:0", 5)
    assert start.replaced  # another file's cursor
    inode = page.cursor.split(":")[0]
    first = files.activity_after(KEY, f"{inode}:0", 5)
    assert not first.replaced and 0 < len(first.events) < 100 and first.events[0].text == "message 000"


def test_the_sink_never_fails_the_run_when_the_file_cannot_be_written(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    (tmp_path / "attempts").write_text("a file where the directory must go")
    run(files, events.Msg(text="x"), events.Cmd(id="c", text="ls"))
    assert not files.activity_tail(KEY, 10).available
