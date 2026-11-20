"""A step's admitted input from its workflow sections: the sections in file order, each a verbatim `text` or a renderer
(`task`, `input_context`), then the step kind's contract, which code owns and appends. Nothing here reads or writes."""

from taskloop.input_context import InputContext
from taskloop.task import TaskInspection
from taskloop.workflow import Renderer, Steps, StepTable


def render(table: StepTable, task: TaskInspection, context: InputContext, contract: str) -> str:
    """The sections joined by blank lines, then `contract`."""
    parts: list[str] = []
    for section in table.prompt:
        match section.use:
            case Renderer.TASK:
                parts.append(f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}")
            case Renderer.INPUT_CONTEXT:
                parts.append(context.render())
            case None:
                parts.append(section.text or "")
    return "\n\n".join([*parts, contract]) + "\n"


def feedback_opening(steps: Steps) -> str:
    """The failed-check input's workflow sections, verbatim and joined by blank lines; code appends the evidence."""
    return "\n\n".join(each.text or "" for each in steps.feedback)
