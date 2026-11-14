"""Explicit start and scheduling rounds continue published plans after independent main landings."""

import json
import sqlite3
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from beads_client import Bead
from doubles import MAIN_PROFILE, FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import MergeRepo
from round_bench import Factory, Tracker, scripted

from taskloop.merge.models import Phase
from taskloop.merge.store import MergeStore


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "old main\n", ".task-loop.json": json.dumps(MAIN_PROFILE)})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return MergeRepo.clone(remote, tmp_path / "main")


@pytest.mark.parametrize("mode", ["explicit", "round"])
def test_implementation_starts_with_its_published_plan_and_main_without_another_plan(
    factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
    slot_files: FakeSlotFiles, checkouts: PinnedViews, tmp_path: Path, mode: str,
) -> None:
    tracker = Tracker(Bead("tl-1", title="Keep the plan and main", description="Implement the retained plan", labels=("auto",)))
    case = Factory(factory, tmp_path, slot, checkouts, slot_files, tracker)
    case.merge_before_dispatch = True
    path = "docs/design/tl-1/plan.md"
    case.agents["tl-1", "plan"] = scripted(repo, {"disposition": "planned", "plan_path": path,
                     "paths": [path], "message": "Plan tl-1", "explanation": "Plan retained."}, {path: "# Retained plan\n"})
    case.by_hand("tl-1")
    original = case.tip("tl-1")
    target = remote.advance("main", {"other": "another task landed\n"})
    assert repo.fetch().ok
    slot.park(target)  # every free slot is on the new main; local main deliberately lags

    def implementation(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        here = repo.worktree(Path(spec.cwd or ""))
        assert here.read_file(path) == "# Retained plan\n" and here.read_file("other") == "another task landed\n"
        return scripted(repo, {"disposition": "implemented", "paths": ["code.py"], "message": "Implement retained plan",
                               "explanation": "Both changes retained."}, {"code.py": "value = 1\n"})(harness, spec, timeout, hooks)

    case.agents["tl-1", "implement"] = implementation
    if mode == "explicit":
        case.by_hand("tl-1")
    else:
        case.round()
        case.round()  # verification, release and publication of the implementation
    assert factory.execute("SELECT step FROM attempt ORDER BY seq").fetchall() == [("plan",), ("implement",)]
    assert len(case.ran) == 2 and tracker.claims == ["tl-1"]
    final = case.tip("tl-1")
    assert repo.is_ancestor(original, final) and repo.is_ancestor(target, final)
    work = MergeStore(lambda: factory).get(case.current("tl-1"))
    assert work is not None and work.phase is Phase.COMPLETE and work.source == original and work.target == target
    assert factory.execute("SELECT count(*) FROM published_branch").fetchone() == (2,)
    assert factory.execute("SELECT count(*) FROM task_hold").fetchone() == (0,)


def test_sequential_main_landings_do_not_restart_several_waiting_plans(
    factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
    slot_files: FakeSlotFiles, checkouts: PinnedViews, tmp_path: Path,
) -> None:
    tasks = ("tl-1", "tl-2", "tl-3")
    tracker = Tracker(*(Bead(task, title="Retain waiting work", labels=("auto",)) for task in tasks))
    case = Factory(factory, tmp_path, slot, checkouts, slot_files, tracker)
    case.merge_before_dispatch = True
    for task in tasks:
        path = f"docs/design/{task}/plan.md"
        case.agents[task, "plan"] = scripted(repo, {"disposition": "planned", "plan_path": path,
            "paths": [path], "message": f"Plan {task}", "explanation": "Retained plan."}, {path: f"# Plan {task}\n"})
        case.agents[task, "implement"] = scripted(repo, {"disposition": "implemented", "paths": [f"{task}.py"],
            "message": f"Implement {task}", "explanation": "Completed retained work."}, {f"{task}.py": "value = 1\n"})
        case.by_hand(task)
    for index, task in enumerate(tasks):
        target = remote.advance("main", {f"land-{index}.txt": "another task landed\n"})
        assert repo.fetch().ok
        slot.park(target)
        case.by_hand(task)
        assert repo.is_ancestor(target, case.tip(task))
    assert factory.execute("SELECT task_id,count(*) FROM attempt GROUP BY task_id ORDER BY task_id").fetchall() == [
        (task, 2) for task in tasks]
    assert tracker.claims == list(tasks) and factory.execute("SELECT count(*) FROM task_hold").fetchone() == (0,)
