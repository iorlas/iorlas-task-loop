"""The one recovery after `refused:conflict` (tl-8bh9.14.8 section 13): the person brings `main` up to date, sets the
stale `task/<id>` aside (locally and on origin), abandons and restarts; the restarted chain is planned and implemented on
the current `main`, so its commit squashes onto origin's `main` without a conflict. Over the rounds bench (real SQLite,
admission, release and publish; the semantic Git fake and its remote)."""

import sqlite3
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import Sha, Squashed
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from round_bench import Factory, Tracker, scripted, task

from taskloop.attempt_types import SlotFiles


@pytest.fixture
def remote() -> FakeRemote:
    made = FakeRemote("https://example.invalid/repo.git")
    made.advance("main", {"README": "one"})
    return made


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def factory(factory: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Factory:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    plan, code = "docs/design/tl-1/plan.md", "src/shared.py"
    built.agents["tl-1", "plan"] = scripted(
        slot.repo, {"disposition": "planned", "plan_path": plan, "paths": [plan], "message": "Plan", "explanation": "planned"},
        {plan: "# Plan\n"})
    built.agents["tl-1", "implement"] = scripted(
        slot.repo, {"disposition": "implemented", "paths": [code], "message": "Add it", "explanation": "ran just check"},
        {code: "X = 1\n"})
    return built


def run_to_implemented(factory: Factory) -> None:
    """Plan, advance, implement: three rounds, then the check step's skip (this `main` requires no check)."""
    for _ in range(4):
        factory.round()


def test_a_task_whose_x_conflicts_with_a_moved_main_is_restarted_on_the_new_main_and_squashes_clean(
        factory: Factory, remote: FakeRemote) -> None:
    run_to_implemented(factory)
    repo, first = factory.slot.repo, factory.tip("tl-1")
    moved = remote.advance("main", {"src/shared.py": "X = 2\n"}, "someone else lands")
    person = repo.worktree(repo.path)
    repo.fetch()  # the land's own fetch
    assert not isinstance(repo.squash(moved, first, "land"), Squashed)  # `refused:conflict`: the old chain cannot land
    person.merge_ff("origin/main")  # git pull --ff-only
    repo.rename_branch("task/tl-1", "old/task/tl-1")  # git branch -m
    repo.delete_remote_at("origin", "refs/heads/task/tl-1", Sha(first))  # git push origin --delete
    found = factory.store.attempt_of("tasks", "tl-1")
    assert found is not None and factory.releaser().release(found[0], True)  # tl step release --abandon
    factory.agents["tl-1", "implement"] = scripted(
        repo, {"disposition": "implemented", "paths": ["src/shared.py"], "message": "Add it", "explanation": "ran just check"},
        {"src/shared.py": "X = 2\nY = 1\n"})
    factory.by_hand("tl-1")  # tl step start
    run_to_implemented(factory)
    second = factory.tip("tl-1")
    assert second != first and moved in [each.sha for each in repo.history([second])]
    assert isinstance(repo.squash(moved, second, "land"), Squashed)
    assert [name for name, _sha in repo.branches("old/")] == ["old/task/tl-1"]  # the old work is kept
