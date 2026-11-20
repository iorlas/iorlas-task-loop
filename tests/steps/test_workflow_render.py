"""A step's input is the workflow's sections in file order, then the kind's contract, which code owns."""

from taskloop.input_context import InputContext
from taskloop.step import Step
from taskloop.step_text import GIT_WRITES
from taskloop.steps import kind
from taskloop.task import TaskInspection, TaskReference, TaskScope
from taskloop.workflow import Workflow, load
from taskloop.workflow_render import feedback_opening, render

WORKFLOW = load(b"""
[[step.plan.prompt]]
text = "PLAN-FIRST"
[[step.plan.prompt]]
use = "task"
[[step.plan.prompt]]
use = "input_context"
[[step.plan.prompt]]
text = "PLAN-LAST"
[[step.implement.prompt]]
use = "input_context"
[[step.implement.prompt]]
use = "task"
[[step.feedback]]
text = "FIRST WORDS"
[[step.feedback]]
text = "SECOND WORDS"
""")
TASK = TaskInspection(
    TaskReference(TaskScope("tasks"), "tl-1"),
    "Add a widget",
    "It must do X.",
    "- X works",
    (),
    "in_progress",
    "taskloop",
)
CONTEXT = InputContext("a" * 40, ("just check",), "Glossary.\n", ())


def test_sections_render_in_file_order_then_the_contract() -> None:
    assert isinstance(WORKFLOW, Workflow)
    text = render(WORKFLOW.table(Step.PLAN), TASK, CONTEXT, "CONTRACT")
    assert text.index("PLAN-FIRST") < text.index("Add a widget\n\nIt must do X.\n\n- X works") < text.index("BEGIN FACTORY INPUT CONTEXT")
    assert text.index("PLAN-LAST") < text.index("CONTRACT") and text.endswith("CONTRACT\n")


def test_a_kinds_input_is_its_tables_sections_then_its_own_contract() -> None:
    assert isinstance(WORKFLOW, Workflow)
    for step in Step:
        found = kind(step)
        rules = found.rules("tl-1")
        text = found.input_text(WORKFLOW.table(step), TASK, rules, CONTEXT)
        assert "Add a widget" in text and "BEGIN FACTORY INPUT CONTEXT" in text
    plan = kind(Step.PLAN).input_text(WORKFLOW.table(Step.PLAN), TASK, kind(Step.PLAN).rules("tl-1"), CONTEXT)
    assert plan.index("PLAN-LAST") < plan.index("docs/design/tl-1/plan.md")


def test_the_workflow_cannot_remove_the_contract() -> None:
    assert isinstance(WORKFLOW, Workflow)
    for step in Step:
        found = kind(step)
        text = found.input_text(WORKFLOW.table(step), TASK, found.rules("tl-1"), CONTEXT)
        assert GIT_WRITES in text  # appended by code, whatever the file says
        assert f"`{'planned' if step is Step.PLAN else 'implemented'}`" in text


def test_the_feedback_opening_is_its_text_sections_in_file_order_joined_by_blank_lines() -> None:
    assert isinstance(WORKFLOW, Workflow)
    assert feedback_opening(WORKFLOW.step) == "FIRST WORDS\n\nSECOND WORDS"
