"""The starter workflow loads and renders for both agent steps."""

from taskloop.input_context import InputContext
from taskloop.step import Step
from taskloop.task import TaskInspection, TaskReference, TaskScope
from taskloop.workflow import Workflow, load
from taskloop.workflow_render import AttemptBudget, feedback_opening, render
from taskloop.workflow_starter import STARTER

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
    assert feedback_opening(workflow.step, AttemptBudget(2, workflow.implement_cap)).startswith("Failed check\nThe factory's check failed.")


def test_the_starter_names_no_repository_specific_tool() -> None:
    assert not {"just", "uv", "bd", "glossary"} & set(STARTER.lower().replace("`", " ").split())
