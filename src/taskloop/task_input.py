"""The admitted input of a step: the workflow's sections for the step kind, then the kind's contract."""

from taskloop.discussion import empty, replace_block
from taskloop.input_context import InputContext
from taskloop.steps import kind
from taskloop.task import TaskInspection
from taskloop.workflow import Workflow


def task_text(task: TaskInspection, step: str, context: InputContext, workflow: Workflow, discussion: str | None = None) -> str:
    """The step kind's input for the task, stored as the admitted input under its digest."""
    found = kind(step)
    text = found.input_text(workflow.table(found.step), task, found.rules(task.reference.task_id), context)
    return replace_block(text, empty(task, "").text if discussion is None else discussion)
