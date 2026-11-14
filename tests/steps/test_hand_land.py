"""Hand-started and labelled checks share delivery and status, through the application operations."""

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from land_bench import PROFILE, LandBench, bench
from round_bench import Factory, Tracker, scripts, task
from test_dash_read import Tracker as DashTracker

from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_status import Listed, Shown, StatusPorts, current_view, list_attempts, show_attempt
from taskloop.check_release import ChecksRelease
from taskloop.check_store import CheckStore
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_model import Board, TaskDetail
from taskloop.dash_task import TaskPorts, build_task
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.land import How, Landed, LandRequest, land
from taskloop.land_mode import known_mode, known_slot_mode, land_mode
from taskloop.land_status import LandState
from taskloop.operations import Failed, Round
from taskloop.profile import LandMode
from taskloop.result_data import as_data
from taskloop.round import NextRequest, RoundPorts, run_round
from taskloop.round_land import Landing
from taskloop.slot_lock import custody
from taskloop.step_render import human
from taskloop.task_status import Status, task_status, words


@pytest.fixture
def b(tmp_path: Path) -> Iterator[LandBench]:
    built = bench(tmp_path)
    yield built
    built.con.close()


def ports(b: LandBench) -> RoundPorts:
    factory = Factory(b.con, b.root / "art", b.slot, b.views, b.files, Tracker(), adopted=True)
    built = factory.ports()

    def deliver(request: LandRequest) -> How | Failed:
        result = land(b.ports(), request)
        assert isinstance(result, (Landed, Failed))
        return result.how if isinstance(result, Landed) else result

    reads = replace(built.reads, policy=known_slot_mode(b.views, b.files))
    return replace(built, reads=reads, landing=Landing(land_mode(b.views), deliver))


def run(b: LandBench, built: RoundPorts) -> Round | Failed:
    return run_round(built, NextRequest("tasks", "/tracker", b.repo.path, "auto", StepSettings(), Overrides(), 30))


def snapshot(reads: StatusPorts, b: LandBench) -> None:
    listed = list_attempts(reads)
    assert isinstance(listed, Listed)
    view = listed.attempts[0]
    status = task_status(view)
    note = words(status)
    tracker, files = DashTracker(), EvidenceFiles(b.root / "art")
    board = build_board(BoardPorts(reads, files, tracker))
    detail = build_task(TaskPorts(reads, files, tracker), "tasks", "tl-1")
    assert isinstance(board, Board) and isinstance(detail, TaskDetail)
    assert board.tasks[0].status == detail.task.status == status.status.value
    assert board.tasks[0].status_note == detail.task.status_note == note
    assert board.tasks[0].land == detail.task.land == status.land
    data = as_data(listed)
    assert note in "\n".join(human("tl step list", listed, None))
    assert f'"status_note": "{note}"' in json.dumps(data)
    shown = show_attempt(reads, b.root / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown)
    assert as_data(shown)["status_note"] == note
    assert f"Status: {note}" in human("tl step show", shown, None)


@pytest.mark.parametrize("label", [None, "auto"])
@pytest.mark.parametrize(("policy", "state", "explanation"), [
    ("auto", LandState.WAITING, "waits for the factory"),
    ("manual", LandState.MANUAL, "waits for a person"),
    (None, LandState.MANUAL, "waits for a person"),
    ("invalid", LandState.UNKNOWN, "landing policy is unavailable"),
    ("missing", LandState.UNKNOWN, "landing policy is unavailable"),
])
def test_policy_and_label_matrix_lands_once_or_waits_with_matching_status(
    b: LandBench, label: str | None, policy: str | None, state: LandState, explanation: str,
) -> None:
    b.con.execute("UPDATE attempt SET label=?", (label,))
    profile = PROFILE | ({} if policy is None else {"land": policy})
    b.advance({".task-loop.json": None if policy == "missing" else json.dumps(profile)})
    land_mode(b.views)(b.repo.path)  # establish the last-known origin main before the read-only status snapshot
    built = ports(b)
    view = current_view(built.reads, "tasks", "tl-1")
    assert view is not None and view.repo_id == b.repo.identity().key
    assert task_status(view).land is state and explanation in words(task_status(view))
    before = (b.repo.pushes, list(b.tracker), b.origin_main())
    snapshot(built.reads, b)
    assert (b.repo.pushes, b.tracker, b.origin_main()) == before
    for _ in range(3):
        assert isinstance(run(b, ports(b)), Round)  # new ports: no in-memory delivered set survives
    snapshot(ports(b).reads, b)
    final = current_view(ports(b).reads, "tasks", "tl-1")
    assert final is not None
    if policy == "auto":
        assert task_status(final).status is Status.LANDED
        assert b.repo.pushes == 1 and len(b.tracker) == 1 and b.status == "closed"
        assert isinstance(b.land(), Landed) and b.repo.pushes == 1 and len(b.tracker) == 1
    else:
        assert task_status(final).land is state and b.repo.pushes == 0 and b.tracker == []
    assert b.con.execute("SELECT step FROM attempt").fetchall() == [("implement",)]
    assert b.con.execute("SELECT count(*) FROM checks_attempt").fetchone() == (1,)


@pytest.mark.parametrize("label", [None, "auto"])
def test_round_resumes_recorded_delivery_before_close_without_another_push(b: LandBench, label: str | None) -> None:
    b.con.execute("UPDATE attempt SET label=?", (label,))
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})

    def interrupted() -> None:
        b.on_close = lambda: None
        raise KeyboardInterrupt

    b.on_close = interrupted
    with pytest.raises(KeyboardInterrupt):
        run(b, ports(b))
    assert b.repo.pushes == 1 and b.rows()[-1].delivery is not None and b.rows()[-1].close is None
    assert isinstance(run(b, ports(b)), Round)
    assert isinstance(run(b, ports(b)), Round)
    assert b.repo.pushes == 1 and len(b.tracker) == 1 and b.status == "closed"
    snapshot(ports(b).reads, b)


@pytest.mark.parametrize("foreign", ["backlog", "repo_id"])
def test_round_does_not_land_another_repository_or_backlog(b: LandBench, foreign: str) -> None:
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})
    b.con.execute(f"UPDATE attempt SET {foreign}='other'")
    assert isinstance(run(b, ports(b)), Round)
    assert b.repo.pushes == 0 and not b.tracker


def test_policy_is_read_from_committed_origin_main_and_checks_repository_identity(b: LandBench) -> None:
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})
    assert land_mode(b.views)(b.repo.path) is LandMode.AUTO
    b.repo.worktree(b.repo.path).write_file(".task-loop.json", json.dumps(PROFILE | {"land": "manual"}))
    b.slot.checkout_new("task/another")  # the slot no longer contains the checked task
    b.remote.offline = True  # status must use the known local ref, with no fetch
    mode = known_slot_mode(b.views, b.files)
    assert mode(b.slot.path, b.repo.identity().key) is LandMode.AUTO
    assert mode(b.slot.path, "another-repository") is None
    assert mode(b.root / "missing", b.repo.identity().key) is None
    assert known_mode(b.views)(b.repo.path) is LandMode.AUTO
    assert b.repo.pushes == 0 and b.tracker == []


def test_round_lands_checks_released_during_its_settle_phase(b: LandBench) -> None:
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})
    store = CheckStore(lambda: b.con)
    checks = store.of_attempt("implement")[-1]
    b.con.execute("UPDATE checks_attempt SET released_at=NULL,parked=NULL")
    b.con.execute("INSERT INTO reservation (slot,repo_id,generation,attempt_id) VALUES ('s1',?,?,?)",
                  (b.repo.identity().key, checks.key.reservation_generation, checks.key.attempt_id))
    releaser = ChecksRelease(store, b.views, b.files, lambda _entry: "gone", custody, lambda: b.now,
                             lambda _process: "gone", lambda _scratch: True, ids=NativeIds())
    built = ports(b)
    built = replace(built, starting=replace(built.starting, checks=replace(built.starting.checks, release=releaser)))
    result = run(b, built)
    assert isinstance(result, Round)
    assert [(move.action, move.word) for move in result.moves] == [("release", "released"), ("land", "pushed")]
    assert b.repo.pushes == 1 and len(b.tracker) == 1 and b.status == "closed"


def test_completed_delivery_frees_capacity_for_a_new_task_in_the_same_round(b: LandBench) -> None:
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})
    factory = Factory(b.con, b.root / "art", b.slot, b.views, b.files, Tracker(task("tl-2")), adopted=True)
    scripts(factory, b.slot, "tl-2")
    built = replace(factory.ports(), landing=ports(b).landing)
    request = NextRequest("tasks", "/tracker", b.repo.path, "auto", StepSettings(), Overrides(model="m", effort="high"),
                          30, max_running=1)
    result = run_round(built, request)
    assert isinstance(result, Round)
    assert [(move.task_id, move.action, move.word) for move in result.moves if move.action in ("land", "start")] == [
        ("tl-1", "land", "pushed"), ("tl-2", "start", "started")]
    assert b.repo.pushes == 1 and len(b.tracker) == 1


@pytest.mark.parametrize("excluded", ["failed", "abandoned", "unreleased", "running"])
def test_round_does_not_deliver_ineligible_checks(b: LandBench, excluded: str) -> None:
    b.advance({".task-loop.json": json.dumps(PROFILE | {"land": "auto"})})
    if excluded == "failed":
        b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    elif excluded == "abandoned":
        b.con.execute("UPDATE checks_attempt SET abandoned=1")
    elif excluded == "unreleased":
        b.con.execute("UPDATE checks_attempt SET released_at=NULL,parked=NULL")
    else:
        b.con.execute("UPDATE checks_attempt SET entry_pid=7,entry_start='start',entry_boot='boot'")
    built = ports(b)
    if excluded in ("running", "unreleased"):
        if excluded == "unreleased":
            b.con.execute("UPDATE checks_attempt SET entry_pid=7,entry_start='start',entry_boot='boot'")
        built = replace(built, reads=replace(built.reads, observe=lambda _entry: "matching"))
    assert isinstance(run(b, built), Round)
    assert b.repo.pushes == 0 and b.tracker == []
