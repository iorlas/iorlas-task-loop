"""The starter workflow loads and renders for both agent steps; `scaffold` writes it once, uncommitted, never over a file."""

from pathlib import Path

from git_porcelain.testing import FakeRemote, FakeRepo

from taskloop.input_context import InputContext
from taskloop.step import Step
from taskloop.task import TaskInspection, TaskReference, TaskScope
from taskloop.workflow import Workflow, load
from taskloop.workflow_render import feedback_opening, render
from taskloop.workflow_starter import STARTER, Created, Exists, scaffold, starter_path

TASK = TaskInspection(
    TaskReference(TaskScope("tasks"), "tl-1"),
    "Add a widget",
    "It must do X.",
    "- X works",
    (),
    "in_progress",
    "taskloop",
)
CONTEXT = InputContext("a" * 40, ("make check",), "Glossary.\n", ())


def test_the_starter_loads_and_renders_for_each_step() -> None:
    workflow = load(STARTER.encode())
    assert isinstance(workflow, Workflow)
    for step in Step:
        text = render(workflow.table(step), TASK, CONTEXT, "CONTRACT")
        assert text.index("AGENTS.md") < text.index("Add a widget") < text.index("BEGIN FACTORY INPUT CONTEXT")
        assert text.endswith("CONTRACT\n")
    assert feedback_opening(workflow.step).startswith("Failed check\nThe factory's check failed.")


def test_the_starter_names_no_repository_specific_tool() -> None:
    assert not {"just", "uv", "bd", "glossary"} & set(STARTER.lower().replace("`", " ").split())


def test_scaffold_writes_into_the_working_tree_only_and_never_over_a_file(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "one"})
    repo = FakeRepo.clone(remote, tmp_path / "main")
    tree = repo.worktree(repo.path)
    branches = repo.branches()

    def write(path: Path, text: str) -> None:
        relative = str(path.relative_to(repo.path))
        if tree.read_file(relative) is not None:
            raise FileExistsError(path)
        tree.write_file(relative, text)

    created = scaffold(repo.path, "default", write)
    assert created == Created(starter_path(repo.path, "default")) and created.path.name == "default.toml"
    assert tree.read_file(".task-loop/workflows/default.toml") == STARTER
    status = tree.dirty()
    assert status.untracked == (".task-loop/workflows/default.toml",) and not status.tracked
    assert repo.branches() == branches and branches
    assert scaffold(repo.path, "default", write) == Exists(created.path)
    assert tree.read_file(".task-loop/workflows/default.toml") == STARTER
