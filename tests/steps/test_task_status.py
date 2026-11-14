"""The one task status (tl-8bh9.14.143): one status per task computed from its stored facts, the same one in `tl step list`, the
board and the drawer, the queued reasons, and the restart rule for a task a person abandoned."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import D
from test_dash_read import KEY, Tracker

from taskloop.attempt_reads import ReleaseRow
from taskloop.attempt_status import AttemptView, Listed, StatusPorts, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptResult
from taskloop.dash_board import BoardPorts, admission_of, build_board, column_of
from taskloop.dash_model import Board, Ready, TaskDetail
from taskloop.dash_task import TaskPorts, build_task
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_store import HoldRow
from taskloop.land_policy import LandState
from taskloop.step_render import human
from taskloop.task_status import Admission, Status, TaskStatus, Wait, blocker, in_flight, skipped, task_status, words

PASSED = AttemptResult("collected", "passed")
VIEW = AttemptView("tasks", "tl-1", "plan", "a", "s1", "admitted", "running", AttemptResult("pending", "admitted"), False, "wait")
HOLD = HoldRow("a", "a", "failed:needs_owner", 10.0, "not_ours", 11.0, 12.0, 13.0, None, 4, "tasks", "tl-1", "/tracker", "auto")
ABANDONED = replace(VIEW, next="start", entry="gone", release=ReleaseRow(D, 5.0, "unclaimed"))
ASKED = Admission(frozenset({"tl-1"}), "auto")


@pytest.mark.parametrize(("view", "expected"), [
    (VIEW, TaskStatus(Status.RUNNING)),
    (replace(VIEW, step="check"), TaskStatus(Status.CHECKING)),
    (replace(VIEW, next="verify"), TaskStatus(Status.SETTLING, "verify")),
    (replace(VIEW, next="land", step="check"), TaskStatus(Status.WAITING_FOR_LAND, landing=LandState.UNKNOWN)),
    (replace(VIEW, next="landed", step="check"), TaskStatus(Status.LANDED)),
    (replace(VIEW, next="hold", hold=HOLD), TaskStatus(Status.HELD, "failed:needs_owner")),
    (replace(VIEW, next="hold", hold_due="stuck:entry_lost"), TaskStatus(Status.HELD, "stuck:entry_lost")),
    (replace(VIEW, next="on_hold", hold=HOLD), TaskStatus(Status.HELD, "failed:needs_owner")),
    (replace(VIEW, next="stuck:hung"), TaskStatus(Status.STUCK, "stuck:hung")),
    (replace(VIEW, next="done", result=AttemptResult("collected", "rejected:paths")), TaskStatus(Status.STUCK, "failed:rejected:paths")),
    (replace(VIEW, next="done", result=PASSED), TaskStatus(Status.FINISHED)),
    (ABANDONED, TaskStatus(Status.ABANDONED, "start")),
])
def test_each_view_has_one_status_with_its_stored_reason(view: AttemptView, expected: TaskStatus) -> None:
    assert task_status(view) == expected
    assert words(expected)  # every status has plain words


def test_a_task_a_person_abandoned_is_queued_to_start_once_the_tracker_lists_it_under_the_label() -> None:
    assert task_status(ABANDONED, Admission(frozenset(), "auto")).status is Status.ABANDONED  # no approval label on it: stays abandoned
    assert task_status(ABANDONED, ASKED) == TaskStatus(Status.QUEUED, "start", Wait.READY)
    half_done = replace(ABANDONED, next="release", release=ReleaseRow(D, 5.0, "unclaiming"))  # its claim is still being returned
    assert task_status(half_done, ASKED).status is Status.ABANDONED


def test_a_hold_abandon_is_taken_again_only_by_the_answer_to_its_label() -> None:
    held = replace(ABANDONED, next="on_hold", hold=replace(HOLD, labels="moved", label="auto"), release=ReleaseRow(D, 5.0, "unclaimed"))
    assert task_status(held, ASKED).status is Status.QUEUED
    assert task_status(held, replace(ASKED, label="night")).status is Status.HELD  # another round label: not the person's answer
    assert task_status(replace(held, hold=replace(HOLD, labels="not_ours")), ASKED).status is Status.HELD


@pytest.mark.parametrize(("free", "reserve", "running", "bound", "wait"), [
    (0, 0, 0, 3, Wait.NO_FREE_SLOT), (1, 1, 0, 3, Wait.SLOT_FOR_LAND), (2, 1, 3, 3, Wait.MAX_RUNNING), (2, 1, 2, 3, Wait.READY),
])
def test_a_queued_task_says_why_it_does_not_start_yet(free: int, reserve: int, running: int, bound: int, wait: Wait) -> None:
    found = task_status(ABANDONED, replace(ASKED, wait=blocker(free, reserve, running, bound)))
    assert (found.status, found.wait) == (Status.QUEUED, wait)
    assert words(found).startswith("queued to start")


def test_a_skip_by_rule_is_queued_with_the_rule_in_its_words() -> None:
    found = skipped("assigned")
    assert (found.status, found.wait, found.skip) == (Status.QUEUED, Wait.SKIPPED, "assigned") and "assigned" in words(found)


def test_only_work_that_goes_on_without_the_person_is_in_flight() -> None:
    views = (VIEW, replace(VIEW, task_id="tl-2", next="stuck:hung"), replace(ABANDONED, task_id="tl-3"),
             replace(VIEW, task_id="tl-4", next="land"), replace(VIEW, task_id="tl-5", next="hold", hold=HOLD))
    assert in_flight(views) == {"tl-1", "tl-4"}


def abandon(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM reservation")
    con.execute("INSERT INTO slot_release VALUES ('attempt','dispatch',1,?,5,'unclaimed')", (D,))


def reads_of(con: sqlite3.Connection) -> StatusPorts:
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "gone", lambda: 1000.0, lambda _key: None, lambda: "boot")


def test_list_board_and_drawer_agree_on_a_task_a_person_abandoned(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    abandon(registered)
    reads = reads_of(registered)
    listed = list_attempts(reads)
    assert isinstance(listed, Listed) and listed.attempts[0].next == "start"
    row = human("tl step list", listed, None)[1]
    assert "\tabandoned: " in row  # the list does not read the tracker: it cannot know the label
    unlabelled = build_board(BoardPorts(reads, files, Tracker()))
    assert isinstance(unlabelled, Board) and (unlabelled.tasks[0].column, unlabelled.tasks[0].status) == ("waiting", "abandoned")
    ready = Tracker((Ready("tl-1", "back under the label", "2026-11-12T09:00:00Z"),))
    board = build_board(BoardPorts(reads, files, ready))
    assert isinstance(board, Board) and [(c.column, c.status) for c in board.tasks] == [("waiting", "queued")]
    assert board.tasks[0].status_note == "queued to start: the next round starts it"
    detail = build_task(TaskPorts(reads, files, ready), "tasks", "tl-1")
    assert isinstance(detail, TaskDetail) and detail.task.status == "queued"
    assert detail.attempts and all(each.past for each in detail.attempts)  # the abandoned chain is history, not the task's steps


def test_a_running_task_is_not_past_and_has_the_running_status_everywhere(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    reads = StatusPorts(AttemptStore(lambda: registered), lambda _entry: "matching", lambda: 50.0, lambda _key: None, lambda: "boot")
    board = build_board(BoardPorts(reads, files, Tracker()))
    detail = build_task(TaskPorts(reads, files, Tracker()), "tasks", "tl-1")
    assert isinstance(board, Board) and (board.tasks[0].column, board.tasks[0].status) == ("plan", "running")
    assert isinstance(detail, TaskDetail) and not any(each.past for each in detail.attempts)


def test_a_full_board_says_no_free_slot_for_a_queued_task(registered: sqlite3.Connection) -> None:
    found = admission_of(reads_of(registered), frozenset({"tl-1"}))
    assert found.wait is Wait.NO_FREE_SLOT  # the one adopted slot is reserved
    assert column_of(ABANDONED) == "waiting"
