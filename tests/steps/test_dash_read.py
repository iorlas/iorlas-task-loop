"""The dashboard's read model (board and task detail) over the same factory.db reads as `tl step list`: display only."""

import sqlite3
from pathlib import Path

from any_agent import events

from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.command_sink import CommandSink
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_model import Board, Comment, FeedPage, Fields, Ready, TaskDetail
from taskloop.dash_task import TaskPorts, build_feed, build_task
from taskloop.evidence_files import EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)
FIELDS = Fields("P1", ("auto",), "task/tl-1", "taskloop", "2026-11-12T10:00:00Z", "2026-11-12T11:00:00Z", ("tl-0",), "Why", "Done when",
                "", "")


class Tracker:
    """The tracker reads as a fake: what it lists ready, the titles it knows and the one task it can show."""

    def __init__(self, ready: tuple[Ready, ...] = (), problem: str | None = None) -> None:
        self.listed, self.problem = ready, problem

    def ready(self) -> tuple[Ready, ...]:
        return self.listed

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {each: f"Title of {each}" for each in task_ids}

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        return (FIELDS, (Comment("denis", "2026-11-12T10:30:00Z", "Keep it small"),)) if task_id == "tl-1" else None

    def notice(self) -> str | None:
        return self.problem


def reads_of(con: sqlite3.Connection, now: float = 1000.0) -> StatusPorts:
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: now, lambda _key: None, lambda: "boot")


def board_of(con: sqlite3.Connection, files: EvidenceFiles, tracker: Tracker) -> Board:
    found = build_board(BoardPorts(reads_of(con), files, tracker))
    assert isinstance(found, Board)
    return found


def test_the_board_has_a_card_for_each_attempted_task_and_each_ready_task_without_one(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    ready = (Ready("tl-1", "taken already", "2026-11-12T09:00:00Z"), Ready("tl-2", "Second", "2026-11-12T09:30:00Z"))
    board = board_of(registered, files, Tracker(ready))
    cards = {card.id: card for card in board.tasks}
    assert sorted(cards) == ["tl-1", "tl-2"] and board.slots == ("s1",)
    assert (cards["tl-1"].column, cards["tl-1"].title, cards["tl-1"].slot, cards["tl-1"].attempt) == ("plan", "Title of tl-1", "s1", 1)
    assert cards["tl-1"].step_started_at is not None and cards["tl-1"].repeat is None and cards["tl-1"].hold_cause is None
    assert (cards["tl-2"].column, cards["tl-2"].title, cards["tl-2"].attempt, cards["tl-2"].slot) == ("waiting", "Second", 0, None)
    assert cards["tl-2"].step_started_at == "2026-11-12T09:30:00Z"


def test_a_tracker_problem_reaches_the_board_as_a_notice(registered: sqlite3.Connection, tmp_path: Path) -> None:
    board = board_of(registered, EvidenceFiles(tmp_path), Tracker(problem="Tracker unavailable: down"))
    assert board.notice == "Tracker unavailable: down" and [card.id for card in board.tasks] == ["tl-1"]


def test_a_task_detail_has_the_tracker_text_the_comments_and_each_attempts_prompt(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert found.fields.acceptance == "Done when" and [each.author for each in found.comments] == ["denis"]
    (attempt,) = found.attempts
    assert (attempt.step, attempt.n, attempt.after, attempt.input) == ("plan", 1, None, "Plan the actual task")
    assert attempt.state == "running" and attempt.feed[0].type == "step"
    assert found.task.column == "plan" and found.task.title == "Title of tl-1"


def test_a_task_neither_factory_nor_tracker_knows_is_none_and_a_tracker_only_task_has_no_attempts(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    ports = TaskPorts(reads_of(registered), EvidenceFiles(tmp_path), Tracker())
    assert build_task(ports, "tasks", "tl-9") is None


def test_the_checks_attempt_follows_its_implement_attempt_in_the_history(checking: sqlite3.Connection, tmp_path: Path) -> None:
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n) for each in found.attempts] == [("implement", 1), ("checks", 1)]
    assert found.attempts[1].state == "running"


def test_an_agent_attempts_detail_and_feed_show_its_commands_and_messages_as_live_lines(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    sink = CommandSink(files, KEY, iter(range(100, 200, 2)).__next__)
    ports = TaskPorts(reads_of(registered), files, Tracker())
    sink.feed(events.Cmd(id="c1", text="just test"))
    sink.feed(events.CmdEnd(id="c1", text="just test", exit=2))
    sink.feed(events.Msg(text="two checks failed"))
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    (attempt,) = found.attempts
    assert [(line.type, line.state, line.cmd or line.text) for line in attempt.feed[1:]] == [
        ("command", "finished", "just test"), ("message", None, "two checks failed")]
    assert attempt.feed[1].exit_code == 2 and attempt.feed_cursor is not None
    sink.feed(events.Msg(text="done"))
    page = build_feed(ports, "tasks", "tl-1", "plan", 1, attempt.feed_cursor)
    assert isinstance(page, FeedPage) and [line.text for line in page.events] == ["done"] and not page.replaced
    assert build_feed(ports, "tasks", "tl-1", "plan", 7, None) is None


def test_a_poisoned_events_file_does_not_break_the_task_detail(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    sink = CommandSink(files, KEY, iter(range(100, 200, 2)).__next__)
    sink.feed(events.Msg(text="good"))
    with files.events_path(KEY).open("ab") as stream:
        stream.write(b'{"k":"message","s":"finished","at":Infinity,"t":"inf"}\n{"k":"message","s":"finished","at":1e999,"t":"big"}\n')
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [line.text for line in found.attempts[0].feed[1:]] == ["good"]


def test_a_command_still_running_in_an_ended_attempt_is_shown_unfinished(checking: sqlite3.Connection, tmp_path: Path) -> None:
    files, key = EvidenceFiles(tmp_path), AttemptKey("implement", "implement-token", 1)
    CommandSink(files, key, iter(range(100, 200, 2)).__next__).feed(events.Cmd(id="c1", text="make"))
    found = build_task(TaskPorts(reads_of(checking), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    agent = next(each for each in found.attempts if each.step == "implement")
    assert agent.state != "running" and [line.state for line in agent.feed if line.type == "command"] == ["unfinished"]
