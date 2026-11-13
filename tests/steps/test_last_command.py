"""The time since the agent's last command in `tl step show` and `tl step list` (roadmap B10): a live sink notes it in the
attempt's evidence while the agent runs, the status reads it back. Display only: it never changes the `Next` word."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import CodexHarness, Harness, LaunchSpec, LiveSink, RunHooks, RunOutcome, events

from taskloop import composition
from taskloop.attempt_status import Listed, Shown, StatusPorts, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Seen
from taskloop.command_sink import CommandSink, WatchedHooks
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


def sink_of(files: EvidenceFiles, wall: Clock) -> CommandSink:
    return CommandSink(files, KEY, wall)


def seen(con: sqlite3.Connection, files: EvidenceFiles, now: float, entry: Seen = "matching") -> tuple[list[str], list[str], object]:
    """`tl step show`'s lines, `tl step list`'s lines and the listed attempt's JSON `last_command`."""
    reads = StatusPorts(AttemptStore(lambda: con), lambda _entry: entry, lambda: now, lambda _key: None, lambda: "boot",
                        last_command=files.last_command)
    shown, listed = show_attempt(reads, files.root, "tasks", "tl-1"), list_attempts(reads)
    assert isinstance(shown, Shown) and isinstance(listed, Listed)
    rows = as_data(listed)["attempts"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert as_data(shown)["last_command"] == rows[0]["last_command"]
    return human("tl step show", shown, None), human("tl step list", listed, None), rows[0]["last_command"]


def test_a_running_agent_shows_the_seconds_since_its_last_command(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files, clock = EvidenceFiles(tmp_path), Clock(10.0)
    sink = sink_of(files, clock)
    command(sink)
    clock.now = 10.4
    command(sink)
    assert seen(registered, files, 20.0)[2] == 9  # a sub-second command refreshes the timestamp
    clock.now = 13.0
    command(sink)
    sink.end("done")
    show, rows, data = seen(registered, files, 20.0)
    assert "Last command: 7 s ago" in show
    assert rows[0].endswith("\tlast command") and rows[1].endswith("\twait\t-\t7 s ago")
    assert data == 7


@pytest.mark.parametrize(("evidence", "word"), [(None, "none"), ("not a record\n", "unreadable"), ("", "none")])
def test_no_or_unreadable_evidence_shows_its_word(registered: sqlite3.Connection, tmp_path: Path, evidence: str | None, word: str) -> None:
    files = EvidenceFiles(tmp_path)
    if evidence is not None:
        path = files.events_path(KEY)
        path.parent.mkdir(parents=True)
        path.write_text(evidence)
    show, rows, data = seen(registered, files, 20.0)
    assert f"Last command: {word}" in show and rows[1].endswith(f"\twait\t-\t{word}")
    assert data == word


@pytest.mark.parametrize("entry", ["gone", "different_process", "unknown"])
def test_an_agent_that_cannot_be_running_shows_no_time_even_with_a_stored_worker(
    registered: sqlite3.Connection, tmp_path: Path, entry: Seen,
) -> None:
    files = EvidenceFiles(tmp_path)
    sink = sink_of(files, Clock(10.0))
    command(sink)
    sink.end("done")
    registered.execute("UPDATE attempt SET worker_pid=11,worker_pgid=11,worker_start='start',worker_boot='boot'")
    show, rows, data = seen(registered, files, 20.0, entry=entry)
    assert not any(line.startswith("Last command") for line in show) and rows[1].endswith("\t-") and data is None


def test_an_unregistered_entry_shows_no_command_age(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    sink = sink_of(files, Clock(10.0))
    command(sink)
    sink.end("done")
    registered.execute("UPDATE attempt SET entry_pid=NULL,entry_start=NULL,entry_boot=NULL")
    show, rows, data = seen(registered, files, 20.0)
    assert not any(line.startswith("Last command") for line in show) and rows[1].endswith("\t-") and data is None


def test_a_failed_write_never_fails_the_run(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    files = EvidenceFiles(blocked)
    sink = sink_of(files, Clock(1.0))
    command(sink)
    command(sink)
    sink.end("done")
    assert files.last_command(KEY) == "unreadable"


def test_a_directory_that_escapes_the_evidence_root_never_fails_the_run(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "attempts").symlink_to(outside, target_is_directory=True)
    files = EvidenceFiles(root)
    command(sink_of(files, Clock(1.0)))
    assert files.last_command(KEY) == "unreadable" and not list(outside.iterdir())


def test_each_start_is_recorded_even_when_the_wall_clock_moves_backwards(tmp_path: Path) -> None:
    files, wall = EvidenceFiles(tmp_path), Clock(100.0)
    sink = sink_of(files, wall)
    command(sink)
    wall.now = 100.5
    command(sink)
    assert files.last_command(KEY) == 100.5
    wall.now = 6.0
    command(sink)
    sink.end("done")
    assert files.last_command(KEY) == 6.0
    assert sorted(each.name for each in (tmp_path / files.directory(KEY)).iterdir()) == ["events.jsonl"]


def test_only_a_command_counts(tmp_path: Path) -> None:
    files, sink = EvidenceFiles(tmp_path), sink_of(EvidenceFiles(tmp_path), Clock(1.0))
    for other in (events.Msg(text="thinking"), events.CmdEnd(id="1", text="just test", exit=0), events.Think(text="hm"),
                  events.Tool(id="tool", name="read", arg="README"), events.ToolEnd(id="tool", name="read"),
                  events.WaitingForNetwork(), events.Stall(secs=10), events.HarnessError(text="oops")):
        sink.feed(other)
    sink.end("done")
    assert files.last_command(KEY) == "none"


def test_completions_and_other_activity_do_not_refresh_the_latest_start(tmp_path: Path) -> None:
    files, wall = EvidenceFiles(tmp_path), Clock(10.0)
    sink = sink_of(files, wall)
    sink.feed(events.Cmd(id="a", text="first"))
    wall.now = 11.0
    sink.feed(events.Cmd(id="b", text="second"))
    wall.now = 12.0
    sink.feed(events.CmdEnd(id="b", text="second", exit=0))
    wall.now = 13.0
    sink.feed(events.CmdEnd(id="a", text="first", exit=0))
    wall.now = 20.0
    sink.feed(events.CmdEnd(id="orphan", text="unknown start", exit=0))
    sink.feed(events.Msg(text="finished"))
    sink.feed(events.Tool(id="t", name="read"))
    sink.feed(events.WaitingForNetwork())
    sink.end("done")
    assert files.last_command(KEY) == 11.0


def test_reused_harness_ids_across_sinks_select_the_latest_appended_start(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    first = sink_of(files, Clock(100.0))
    command(first)
    first.end("done")
    resumed = sink_of(files, Clock(5.0))
    command(resumed)
    resumed.feed(events.CmdEnd(id="1", text="just test", exit=0))
    resumed.end("done")
    assert files.last_command(KEY) == 5.0


def test_a_future_command_start_clamps_displayed_seconds_to_zero(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    sink = sink_of(files, Clock(1000.0))
    command(sink)
    sink.end("done")
    show, rows, data = seen(registered, files, 20.0)
    assert "Last command: 0 s ago" in show and rows[1].endswith("\twait\t-\t0 s ago") and data == 0


@pytest.mark.parametrize(("now", "next_word"), [(20.0, "wait"), (200.0, "stuck:hung")])
def test_command_evidence_changes_only_display_even_after_the_deadline(
    registered: sqlite3.Connection, tmp_path: Path, now: float, next_word: str,
) -> None:
    stored = tuple(registered.iterdump())
    displays: list[int | str | None] = []
    baseline = None
    for name, at in (("absent", None), ("recent", now - 0.5), ("old", -1000.0), ("unreadable", None)):
        files = EvidenceFiles(tmp_path / name)
        if at is not None:
            sink = sink_of(files, Clock(at))
            command(sink)
            sink.end("done")
        elif name == "unreadable":
            path = files.events_path(KEY)
            path.parent.mkdir(parents=True)
            path.write_text("broken complete record\n")
        reads = StatusPorts(AttemptStore(lambda: registered), lambda _entry: "matching", lambda: now,
                            lambda _key: None, lambda: "boot", last_command=files.last_command)
        shown, listed = show_attempt(reads, files.root, "tasks", "tl-1"), list_attempts(reads)
        assert isinstance(shown, Shown) and isinstance(listed, Listed)
        view = shown.view
        assert view.next == next_word and view.deadline_passed == (now >= 100)
        displays.append(view.last_command)
        facts = replace(view, last_command=None)
        baseline = facts if baseline is None else baseline
        assert facts == baseline == replace(listed.attempts[0], last_command=None)
        assert tuple(registered.iterdump()) == stored
    assert displays == ["none", 0, int(now + 1000), "unreadable"]


def test_the_production_run_hands_the_attempts_live_sink_to_the_shelf_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    given: list[object] = []

    def shelf(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None, *, live: LiveSink | None = None) -> RunOutcome:
        given.append(live)
        return RunOutcome(rc=0)

    monkeypatch.setattr(composition, "run", shelf)
    sink = sink_of(EvidenceFiles(tmp_path), Clock(1.0))
    composition._run(CodexHarness(), LaunchSpec(argv=[], env={}, cwd="", stdin=""), 1.0, WatchedHooks(live=sink))
    composition._run(CodexHarness(), LaunchSpec(argv=[], env={}, cwd="", stdin=""), 1.0, RunHooks())
    assert given == [sink, None]
