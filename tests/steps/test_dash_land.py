"""Delivery inspection uses the real land summary over semantic collaborators, without delivering."""

import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest
from land_bench import LandBench, bench

from taskloop.dash_land import build_land
from taskloop.dash_model import LandDetail
from taskloop.operations import Failed


@pytest.fixture
def b(tmp_path: Path) -> Iterator[LandBench]:
    world = bench(tmp_path)
    yield world
    world.con.close()


def read(b: LandBench) -> LandDetail:
    found = build_land(b.ports(), "tasks", "tl-1", b.repo.path)
    assert isinstance(found, LandDetail)
    return found


def test_inspecting_delivery_explains_actions_diff_and_command_without_delivering(b: LandBench) -> None:
    found = read(b)
    assert any("Integrate" in action for action in found.actions)
    assert any("Mark the task complete" in action for action in found.actions)
    assert (found.diff_files, found.added, found.deleted) == (1, 1, 0)
    assert shlex.split(found.diff_command) == ["git", "diff", f"{b.base}..{b.x}"]
    assert shlex.split(found.command) == ["tl", "step", "land", "tl-1", "--backlog", "tasks", "--checkout", str(b.repo.path)]
    assert found.pr_url is None
    assert any("src/x.py" in line for line in found.summary)
    assert b.rows() == () and b.reservations() == [] and b.repo.pushes == 0 and b.origin_main() == b.base
    assert b.tracker == [] and b.status == "in_progress" and b.execs() == []


def test_a_moved_main_explains_validation_and_a_conflict_has_no_invented_diff_totals(b: LandBench) -> None:
    b.advance({"OTHER": "another task\n"})
    found = read(b)
    assert any("Validate" in action for action in found.actions) and found.command.endswith("--minutes N")
    b.advance({"src/x.py": "X = 2\n"})
    conflict = read(b)
    assert any("blocked by conflicts" in action for action in conflict.actions)
    assert conflict.diff_files is conflict.added is conflict.deleted is None
    assert b.repo.pushes == 0 and b.execs() == []


def test_already_integrated_changes_and_failed_checks_explain_their_next_actions(b: LandBench) -> None:
    b.advance({"src/x.py": "X = 1\n"})
    found = read(b)
    assert found.command.endswith("--no-change") and any("main already contains" in action for action in found.actions)
    b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    failed = read(b)
    assert any("blocked until" in action for action in failed.actions)
    assert b.rows() == () and b.tracker == []


def test_summary_refusals_keep_the_owning_operations_explanation(b: LandBench) -> None:
    found = build_land(b.ports(), "tasks", "missing", b.repo.path)
    assert isinstance(found, Failed) and found.detail == "The task's current attempt is not a done implement attempt."
    assert b.rows() == () and b.repo.pushes == 0
