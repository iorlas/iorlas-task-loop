"""Reading the workflow file from Git at a commit: found, missing, not a regular file, unusable, Git unreadable."""

from pathlib import Path

import pytest

from taskloop.input_context import InputError
from taskloop.profile import NoCommit, NotAFile, Unavailable
from taskloop.workflow import Reason, Workflow
from taskloop.workflow_read import DEFAULT, DIRECTORY, Pin, WorkflowRefusal, read_workflow

PATH = f"{DIRECTORY}{DEFAULT}.toml"
REPO_FILE = Path(__file__).resolve().parents[2] / PATH


type Answer = bytes | NotAFile | Unavailable | NoCommit | None


class Files:
    def __init__(self, answer: Answer) -> None:
        self.answer, self.asked = answer, []

    def blob(self, commit: str, path: str) -> Answer:
        self.asked.append((commit, path))
        return self.answer


def test_the_repo_default_workflow_loads_and_is_read_from_the_commit() -> None:
    files = Files(REPO_FILE.read_bytes())
    found = read_workflow(files, "c" * 40)
    assert isinstance(found, Pin) and isinstance(found.workflow, Workflow) and found.sha == "c" * 40
    assert files.asked == [("c" * 40, PATH)]


def test_attempt_budget_workflow_differs_from_default_only_by_its_first_feedback_section() -> None:
    default = REPO_FILE.read_bytes()
    variant = REPO_FILE.with_name("attempt-budget.toml").read_bytes()
    section = b'[[step.feedback]]\nuse = "attempt_budget"\n\n'
    assert variant == default.replace(b"[[step.feedback]]", section + b"[[step.feedback]]", 1)
    found = read_workflow(Files(variant), "c" * 40, "attempt-budget")
    assert found.workflow.step.feedback[0].use is not None
    assert found.workflow.implement_cap == 3


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (None, Reason.MISSING),
        (NotAFile("120000"), Reason.NOT_A_FILE),
        (b"= =", Reason.NOT_TOML),
    ],
)
def test_a_missing_or_unusable_file_is_a_typed_refusal(answer: Answer, reason: Reason) -> None:
    with pytest.raises(WorkflowRefusal) as raised:
        read_workflow(Files(answer), "c" * 40)
    assert raised.value.refused.reason is reason


@pytest.mark.parametrize("answer", [Unavailable("git died"), NoCommit()])
def test_git_that_cannot_be_read_is_an_input_error_not_a_refusal(answer: Answer) -> None:
    with pytest.raises(InputError):
        read_workflow(Files(answer), "c" * 40)
