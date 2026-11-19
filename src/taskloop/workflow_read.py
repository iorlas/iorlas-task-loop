"""Reading a workflow file from Git at a commit: the one place that finds `.task-loop/workflows/<name>.toml`."""

import hashlib
from dataclasses import dataclass
from typing import Final

from taskloop.input_context import InputError
from taskloop.profile import NoCommit, NotAFile, ProfileFiles, Unavailable
from taskloop.workflow import Reason, Workflow, WorkflowRefused, load

DIRECTORY: Final = ".task-loop/workflows/"
DEFAULT: Final = "default"


def plain_name(value: str) -> bool:
    """A plain lowercase file name: letters, digits, `-` and `_`, so it can never name a path, a ref or a flag."""
    plain = value.replace("-", "").replace("_", "").isalnum() and value.isascii() and value == value.lower()
    return plain and value[0].isalnum()


class WorkflowRefusal(Exception):
    """The file at the commit is missing or unusable; `refused` says why."""

    def __init__(self, refused: WorkflowRefused) -> None:
        super().__init__(f"{refused.reason}: {refused.where}" if refused.where else str(refused.reason))
        self.refused = refused


@dataclass(frozen=True)
class Pin:
    """The workflow file as one task uses it: its bytes, the commit they were read at and the parsed file. The digest of
    the bytes names the stored copy; the same bytes can sit at two commits, so the commit is kept apart."""

    sha: str
    content: bytes
    workflow: Workflow

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def pinned(content: bytes, sha: str) -> Pin:
    """The pin of `content`; bytes that are not a usable workflow raise `WorkflowRefusal`."""
    loaded = load(content)
    if isinstance(loaded, WorkflowRefused):
        raise WorkflowRefusal(loaded)
    return Pin(sha, content, loaded)


def read_workflow(files: ProfileFiles, commit: str, name: str = DEFAULT) -> Pin:
    """The workflow `name` at `commit`, never the working tree's. A file that is missing or unusable raises
    `WorkflowRefusal`; Git that cannot be read raises `InputError` (reading again is safe)."""
    path = f"{DIRECTORY}{name}.toml"
    blob = files.blob(commit, path)
    match blob:
        case bytes():
            return pinned(blob, commit)
        case None:
            raise WorkflowRefusal(WorkflowRefused(Reason.MISSING, path))
        case NotAFile():
            raise WorkflowRefusal(WorkflowRefused(Reason.NOT_A_FILE, path))
        case Unavailable(detail=detail):
            raise InputError(f"Workflow at {commit}: {detail}")
        case NoCommit():
            raise InputError(f"Workflow source {commit} names no commit")
