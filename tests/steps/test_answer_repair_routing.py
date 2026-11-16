"""CLI start's shared decision and rounds repair once before terminal effects."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain.testing import FakeWorktree
from round_bench import Factory, Tracker, scripts, task
from test_answer_repair import failed as rejected_answer
from test_answer_repair import operation
from test_attempt import ENTRY, KEY, PLAN, AttemptSurroundings, app, fake
from test_attempt import surroundings as attempt_surroundings
from test_operations import FakeLauncher

from taskloop.answer_failures import AnswerRule
from taskloop.answer_repair_models import RepairOutcome
from taskloop.answer_repair_route import AnswerRepairRouting
from taskloop.answer_repair_store import RepairResult
from taskloop.attempt_types import AttemptKey, SlotFiles
from taskloop.hold_store import HoldStore
from taskloop.launch import Launched, LaunchUnavailable
from taskloop.operations import Failed, Started

failed = rejected_answer
surroundings = attempt_surroundings


@pytest.fixture
def factory(factory: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Factory:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(built, slot, "tl-1")
    return built


class Unavailable:
    def admit(self, previous: AttemptKey) -> RepairResult:
        return RepairResult(outcome=RepairOutcome.UNAVAILABLE, explanation="The admission store is unavailable.")


def test_saved_repair_is_adopted_after_launch_failure_without_another_successor(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings,
) -> None:
    admission = operation(failed, surroundings)
    launcher = FakeLauncher(LaunchUnavailable("start"))
    route = AnswerRepairRouting(admission.store, admission, launcher)
    first = route.route("tasks", "tl-1", KEY, 30)
    assert isinstance(first, Failed) and first.admitted
    current = admission.store.attempt_of("tasks", "tl-1")
    assert current is not None and current[0] != KEY
    launcher.result = Launched(current[0], ENTRY)
    second = route.route("tasks", "tl-1", KEY, 30)
    assert isinstance(second, Started) and second.existing and second.attempt_id == current[0].attempt_id
    assert len(admission.store.attempts("tasks", "tl-1")) == 2
    assert len(launcher.calls) == 2


def test_unavailable_admission_defers_terminal_handling(failed: sqlite3.Connection, surroundings: AttemptSurroundings) -> None:
    admission = operation(failed, surroundings)
    launcher = FakeLauncher(Launched(KEY, ENTRY))
    result = AnswerRepairRouting(admission.store, Unavailable(), launcher).route("tasks", "tl-1", KEY, 30)
    assert isinstance(result, Failed) and result.kind == "unavailable" and result.detail
    current = admission.store.attempt_of("tasks", "tl-1")
    assert not launcher.calls and current is not None and current[0] == KEY


def test_invalid_repair_reports_its_latest_rule_and_never_admits_again(
    failed: sqlite3.Connection, surroundings: AttemptSurroundings,
) -> None:
    admission = operation(failed, surroundings)
    repair = admission.admit(KEY)
    assert repair.key is not None
    admission.store.register_entry(repair.key, ENTRY, 10)
    app(failed, surroundings, fake(json.dumps({**PLAN, "paths": ["wrong.md"]}), refs=("saved",))).execute(repair.key, ENTRY)
    launcher = FakeLauncher(Launched(repair.key, ENTRY))
    result = AnswerRepairRouting(admission.store, Unavailable(), launcher).route("tasks", "tl-1", repair.key, 30)
    assert isinstance(result, Failed) and result.kind == "not_applicable"
    assert AnswerRule.PATHS_LOCATION.value in result.detail and "json:" not in result.detail
    assert not launcher.calls and len(admission.store.attempts("tasks", "tl-1")) == 2


def test_round_repairs_then_holds_once_with_the_latest_rule(factory: Factory) -> None:
    first = fake("not json", refs=("saved",))
    factory.agents["tl-1", "plan"] = first
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    original = factory.current("tl-1")
    second = fake(json.dumps({**PLAN, "paths": ["wrong.md"]}), refs=("saved",))
    factory.agents["tl-1", "plan"] = second
    assert factory.round() == [("tl-1", "plan", "repeat", "started")]
    repaired = factory.current("tl-1")
    assert repaired != original and factory.tracker.comments == []
    assert factory.round()[0][2:] == ("hold", "held failed:answer:schema_invalid")
    assert len(factory.tracker.comments) == 1
    comment = factory.tracker.comments[0][1]
    assert "paths_location:" in comment and "json:" not in comment
    for _ in range(2):
        factory.round()
    assert len(first.calls) == len(second.calls) == 1
    assert len(factory.tracker.comments) == 1 and factory.current("tl-1") == repaired


def test_valid_repair_follows_normal_verification(factory: Factory) -> None:
    factory.agents["tl-1", "plan"] = fake("not json", refs=("saved",))
    factory.round()
    scripts(factory, factory.slot, "tl-1")
    assert factory.round()[0][2] == "repeat"
    assert factory.round()[0][2] == "commit"
    assert len(factory.ran) == 2 and not factory.tracker.comments


def test_round_unavailable_admission_and_failed_launch_leave_the_attempt_unheld(factory: Factory) -> None:
    factory.agents["tl-1", "plan"] = fake("not json", refs=("saved",))
    factory.round()
    ports = factory.ports()
    answers = AnswerRepairRouting(factory.store, Unavailable(), factory)
    ports = replace(ports, starting=replace(ports.starting, answer_repair=answers))
    # Use the normal round request while changing only the admission port.
    factory.ports = lambda: ports
    assert factory.round()[0][3] == "unavailable:answer_repair"
    assert not factory.tracker.comments and len(factory.ran) == 1
    answers.admission = operation(factory.con, AttemptSurroundings(factory.tmp, factory.slot, factory.checkouts, factory.files))
    factory.failing = LaunchUnavailable("start")
    assert factory.round()[0][3] == "unavailable:start"
    repair = factory.current("tl-1")
    assert not HoldStore(lambda: factory.con).of_attempts((repair,))
    assert factory.round()[0][2:] == ("relaunch", "relaunched")
    assert factory.current("tl-1") == repair and len(factory.ran) == 2


def test_stale_snapshot_cannot_hold_successor(factory: Factory) -> None:
    factory.agents["tl-1", "plan"] = fake("not json", refs=("saved",))
    factory.round()
    before = factory.current("tl-1")
    factory.agents["tl-1", "plan"] = fake("not json", refs=("saved",))
    ports = factory.ports()
    assert ports.starting.answer_repair is not None
    # The snapshot observer represents another caller admitting after this round's read.
    answers = ports.starting.answer_repair
    current = factory.store.attempt_of("tasks", "tl-1")
    assert current is not None
    factory.during = lambda: answers.route("tasks", "tl-1", current[0], 30)
    factory.round()
    assert factory.current("tl-1") != before and not factory.tracker.comments
    assert not HoldStore(lambda: factory.con).of_attempts((before, factory.current("tl-1")))
    assert factory.round()[0][2] == "hold"
    assert len(factory.tracker.comments) == 1 and len(factory.ran) == 2


def test_expired_original_refuses_repair_and_holds_without_launching(factory: Factory) -> None:
    factory.agents["tl-1", "plan"] = fake("not json", refs=("saved",))
    factory.round()
    factory.now += 2000
    assert factory.round()[0][2] == "hold"
    assert len(factory.ran) == 1 and len(factory.tracker.comments) == 1


def test_execution_failure_keeps_existing_terminal_handling(factory: Factory) -> None:
    factory.agents["tl-1", "plan"] = fake("not json", rc=1, refs=("saved",))
    factory.round()
    assert factory.round()[0][2:] == ("hold", "held failed:run:worker_failed")
    assert len(factory.ran) == 1 and len(factory.tracker.comments) == 1
