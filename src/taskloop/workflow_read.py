"""Reading a workflow file from Git at a commit: the one place that finds `.task-loop/workflows/<name>.toml`."""

from typing import Final

from taskloop.input_context import InputError
from taskloop.profile import NoCommit, NotAFile, ProfileFiles, Unavailable
from taskloop.workflow import Reason, Workflow, WorkflowRefused, load

DIRECTORY: Final = ".task-loop/workflows/"
DEFAULT: Final = "default"


class WorkflowRefusal(Exception):
    """The file at the commit is missing or unusable; `refused` says why."""

    def __init__(self, refused: WorkflowRefused) -> None:
        super().__init__(f"{refused.reason}: {refused.where}" if refused.where else str(refused.reason))
        self.refused = refused


def read_workflow(files: ProfileFiles, commit: str, name: str = DEFAULT) -> Workflow:
    """The workflow `name` at `commit`, never the working tree's. A file that is missing or unusable raises
    `WorkflowRefusal`; Git that cannot be read raises `InputError` (reading again is safe)."""
    path = f"{DIRECTORY}{name}.toml"
    blob = files.blob(commit, path)
    match blob:
        case bytes():
            loaded = load(blob)
        case None:
            raise WorkflowRefusal(WorkflowRefused(Reason.MISSING, path))
        case NotAFile():
            raise WorkflowRefusal(WorkflowRefused(Reason.NOT_A_FILE, path))
        case Unavailable(detail=detail):
            raise InputError(f"Workflow at {commit}: {detail}")
        case NoCommit():
            raise InputError(f"Workflow source {commit} names no commit")
    if isinstance(loaded, WorkflowRefused):
        raise WorkflowRefusal(loaded)
    return loaded
