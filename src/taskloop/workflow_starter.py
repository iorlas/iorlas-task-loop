"""The generic starter workflow `tl workflow init` writes, and the one place that decides where it goes."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from taskloop.workflow_read import DIRECTORY

Writer = Callable[[Path, str], None]  # creates the file and its folders; raises FileExistsError rather than overwrite

_BEFORE: Final = """\
[[step.{kind}.prompt]]
text = \"\"\"\\
Follow the repository's AGENTS.md or README for how to work in it. \\
Assess the task, then {work}. \\
Run the repository's checks listed in the supplied context before you answer.
\"\"\"

[[step.{kind}.prompt]]
use = "task"

[[step.{kind}.prompt]]
use = "input_context"
"""
STARTER: Final = (
    "# A starter workflow: each agent step's prompt, in order. The factory appends its contract after these sections\n"
    "# (answer rules, plan template, Git and commit limits); it is not written here. An agent key (harness, model,\n"
    "# effort, compaction_token_limit) may be added under [step.<kind>.agent]; an absent key falls to machine configuration.\n\n"
    + _BEFORE.format(kind="plan", work="write the plan for the change")
    + "\n"
    + _BEFORE.format(kind="implement", work="make the change the plan describes")
    + """
[[step.feedback]]
text = \"\"\"\\
Failed check
The factory's check failed. Fix the reported failure and run the checks before answering.\"\"\"
"""
)


@dataclass(frozen=True)
class Created:
    path: Path


@dataclass(frozen=True)
class Exists:
    path: Path


def starter_path(checkout: Path, name: str) -> Path:
    return checkout / f"{DIRECTORY}{name}.toml"


def scaffold(checkout: Path, name: str, write: Writer) -> Created | Exists:
    """Write the starter into the checkout's working tree, never over a file: nothing is staged, committed or read from Git."""
    path = starter_path(checkout, name)
    try:
        write(path, STARTER)
    except FileExistsError:
        return Exists(path)
    return Created(path)


def create_new(path: Path, text: str) -> None:
    """The real writer: exclusive create, so a file that exists (or appears meanwhile) is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
