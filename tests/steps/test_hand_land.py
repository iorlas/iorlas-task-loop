"""Hand-started delivery uses the round's land operation and the shared policy presentation."""

from dataclasses import replace
from pathlib import Path

import pytest
from land_bench import LandBench, bench

from taskloop.attempt_status import AttemptView, Listed, StatusPorts, list_attempts
from taskloop.attempt_store import AttemptStore
from taskloop.dash_board import card_of
from taskloop.evidence_files import EvidenceFiles
from taskloop.land import How, Landed, LandRequest, land
from taskloop.land_mode import known_policy, known_slot_policy, land_mode
from taskloop.land_policy import LandPolicy, LandState
from taskloop.land_status import LandView
from taskloop.operations import Failed
from taskloop.profile import LandMode
from taskloop.result_data import as_data
from taskloop.round_land import Landing, land_passed
from taskloop.round_trail import Trail
from taskloop.step_render import human
from taskloop.task_status import Status, task_status, waiting_for_land, words


def views(b: LandBench) -> tuple[AttemptView, ...]:
    store = AttemptStore(lambda: b.con)
    reads = StatusPorts(store, lambda _entry: "gone", lambda: b.now, lambda _key: None, lambda: "boot")
    found = list_attempts(reads)
    assert not isinstance(found, Failed)
    return found.attempts


def test_a_hand_started_task_is_delivered_and_closed_once_without_replanning(tmp_path: Path) -> None:
    b = bench(tmp_path)
    calls: list[LandRequest] = []

    def deliver(request: LandRequest) -> How | Failed:
        calls.append(request)
        found = land(b.ports(), request)
        assert isinstance(found, (Landed, Failed))
        return found if isinstance(found, Failed) else found.how

    landing = Landing(lambda _path: LandMode.AUTO, deliver)
    trail = Trail(lambda _line: None, lambda: b.now, "tasks", None)
    before = b.con.execute("SELECT attempt_id,step FROM attempt").fetchall()
    [view] = views(b)
    assert view.label is None and waiting_for_land(view)
    assert land_passed(landing, "tasks", b.repo.path, 5, (view,), trail, lambda *_args: pytest.fail("unexpected hold")) == {"tl-1"}
    assert land_passed(landing, "tasks", b.repo.path, 5, views(b), trail, lambda *_args: pytest.fail("unexpected hold")) == frozenset()
    assert b.status == "closed" and len(b.tracker) == b.repo.pushes == len(calls) == 1
    assert b.con.execute("SELECT attempt_id,step FROM attempt").fetchall() == before
    assert b.files_of(b.origin_main())["src/x.py"] == "X = 1\n"


@pytest.mark.parametrize("label", [None, "auto"])
@pytest.mark.parametrize("mode", [LandMode.MANUAL, None])
def test_rounds_leave_manual_or_unknown_delivery_to_the_stated_policy(
    tmp_path: Path, label: str | None, mode: LandMode | None,
) -> None:
    b = bench(tmp_path)
    [view] = views(b)
    view = replace(view, label=label, policy=LandPolicy(mode, b.base))

    def deliver(_request: LandRequest) -> How | Failed:
        pytest.fail("manual or unknown policy must not land")

    landing = Landing(lambda _path: mode if mode is not None else Failed("unavailable", "git", "Policy cannot be read."), deliver)
    trail = Trail(lambda _line: None, lambda: b.now, "tasks", None)
    assert not land_passed(landing, "tasks", b.repo.path, 5, (view,), trail, lambda *_args: pytest.fail("unexpected hold"))
    assert task_status(view).landing is (LandState.MANUAL if mode is LandMode.MANUAL else LandState.UNKNOWN)
    assert b.repo.pushes == 0 and b.tracker == [] and b.status == "in_progress"


@pytest.mark.parametrize("label", [None, "auto"])
@pytest.mark.parametrize(("mode", "expected", "note"), [
    (LandMode.AUTO, LandState.WAITING, "Waiting for the factory to land it"),
    (LandMode.MANUAL, LandState.MANUAL, "Waiting for a person to land it (manual policy)"),
    (None, LandState.UNKNOWN, "Landing policy is unavailable"),
])
def test_cli_board_and_drawer_data_convey_the_same_landing_decision(
    tmp_path: Path, label: str | None, mode: LandMode | None, expected: LandState, note: str,
) -> None:
    b = bench(tmp_path)
    [view] = views(b)
    view = replace(view, label=label, policy=LandPolicy(mode, b.base))
    status = task_status(view)
    assert status.status is Status.WAITING_FOR_LAND and status.landing is expected and words(status) == note
    card = card_of(view, None, "Widget", EvidenceFiles(tmp_path), b.now)
    assert (card.land, card.status_note, card.policy_commit) == (expected, note, b.base)
    assert note in "\n".join(human("list", Listed((view,)), None))
    data = as_data(Listed((view,)))["attempts"]
    assert isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)
    assert data[0]["landing"] == {"decision": expected.value, "policy_commit": b.base}
    assert data[0]["status_note"] == note


def test_known_policy_reports_the_immutable_origin_commit_and_never_fetches(tmp_path: Path) -> None:
    b = bench(tmp_path)
    assert known_policy(b.views)(b.repo.path) == LandPolicy(LandMode.MANUAL, b.base)
    b.advance({".task-loop.json": '{"land":"auto","required":[],"checks":[]}'})
    assert known_policy(b.views)(b.repo.path) == LandPolicy(LandMode.MANUAL, b.base)
    assert land_mode(b.views)(b.repo.path) is LandMode.AUTO
    assert known_policy(b.views)(b.repo.path) == LandPolicy(LandMode.AUTO, b.origin_main())



def test_status_reads_policy_at_the_checks_repository_without_fetching(tmp_path: Path) -> None:
    b = bench(tmp_path)
    store = AttemptStore(lambda: b.con)
    reads = StatusPorts(store, lambda _entry: "gone", lambda: b.now, lambda _key: None, lambda: "boot",
                        policy=known_slot_policy(b.views, b.files))
    found = list_attempts(reads)
    assert not isinstance(found, Failed)
    [view] = found.attempts
    assert view.policy == LandPolicy(LandMode.MANUAL, b.base)
    assert task_status(view).landing is LandState.MANUAL



def test_a_redirected_slot_cannot_supply_an_automatic_policy(tmp_path: Path) -> None:
    b = bench(tmp_path)
    b.files.contents[b.slot.path / ".git"] = b"gitdir: /somewhere-else"
    assert known_slot_policy(b.views, b.files)(b.slot.path, b.repo.identity().key) == LandPolicy()



def test_a_candidate_waiting_for_release_still_has_a_renderable_land_state(tmp_path: Path) -> None:
    b = bench(tmp_path)
    [view] = views(b)
    done = b.land()
    assert isinstance(done, Landed)
    releasing = replace(view, next="release", land=LandView(done.row, ()))
    card = card_of(releasing, None, "Widget", EvidenceFiles(tmp_path), b.now)
    assert card.column == "land" and card.land is LandState.FINISHING
