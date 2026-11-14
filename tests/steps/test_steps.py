"""The step kinds: plan then implement, reached through `kind`; their input, repeat framing and attribute files."""

import pytest

from taskloop.admit import task_text
from taskloop.attempt_types import AttemptKey, StepRules, Unsettled
from taskloop.check_repeat.feedback import Availability, FailedCheck, OutputTail
from taskloop.factory_commit import attributes
from taskloop.input_context import InputContext
from taskloop.step_text import GIT_WRITES, SAVED_WORK
from taskloop.steps import IMPLEMENT, ORDER, PLAN, failed_check_feedback, following, is_agent, kind, next_step
from taskloop.task import TaskInspection, TaskReference, TaskScope

CONTEXT = InputContext("a" * 40, ("just check", "just test"), "Partial glossary: task: Work.\n")

TASK = TaskInspection(
    TaskReference(TaskScope("tasks"), "tl-1"), "Add a widget", "It must do X.\nAnd Y.", "- X works\n- Y works", (), "in_progress",
    "taskloop",
)


@pytest.mark.parametrize(("current", "done", "expected"), [
    (None, False, "plan"), (None, True, "plan"), ("plan", True, "implement"), ("implement", True, "check"), ("check", True, None),
    ("plan", False, None), ("implement", False, None),
])
def test_next_step_follows_the_fixed_order_only_after_a_done_step(current: str | None, done: bool, expected: str | None) -> None:
    """None: a fresh start (or after an abandon returned the claim) is the first step; a done step advances; the last
    built step (`check`) is done; an attempt not done keeps its own `Next`."""
    assert next_step(current, done) == expected


def test_the_check_step_follows_implement_and_is_no_agent_kind() -> None:
    """`ORDER` is every built step; only plan and implement have a kind (an agent): `check` is the checks admission's."""
    assert ORDER == ("plan", "implement", "check") and [following(step) for step in ORDER] == ["implement", "check", None]
    assert [is_agent(step) for step in ORDER] == [True, True, False] and not is_agent("review")
    with pytest.raises(ValueError, match="Unknown step"):
        following("review")
    with pytest.raises(ValueError, match="Unknown step"):
        kind("check")


def test_the_implement_input_names_the_committed_plan_its_scope_and_its_environment() -> None:
    """The task's own prose first, then the plan by reference and the rules' scope, then the environment the entry
    prepared: offline setup, `$TMPDIR`, and that only the checks run afterwards count."""
    text = task_text(TASK, "implement", CONTEXT)
    assert text.startswith("Add a widget\n\nIt must do X.\nAnd Y.\n\n- X works\n- Y works\n\n")
    assert "`docs/design/tl-1/plan.md`, committed on this branch by the plan step." in text
    assert "at most 96 files of at most 1 MiB each" in text and "anything under `.beads/`" in text and GIT_WRITES in text
    assert "The factory ran this repository's `setup` before you started; there is no network now." in text
    assert "Temporary files go to `$TMPDIR`, which is emptied after the step; do not write elsewhere outside the repository." in text
    assert (
        "Your runs are evidence for you: after this step the checks run again outside your control, and only those results count. "
        "With `implemented`"
    ) in text
    assert SAVED_WORK in text and text.endswith(SAVED_WORK + "\n")
    assert (
        "In `explanation`, name each command you ran and how it ended, and every test file you added. If you could not finish, "
        "answer `incomplete`; if the plan cannot be implemented as written or needs a decision, answer `needs_owner`; say why "
        "in `explanation`."
    ) in text


def test_the_implement_input_bounds_working_and_final_checks_without_hiding_failures() -> None:
    text = task_text(TASK, "implement", CONTEXT)
    assert "While working, run only focused test files for the code you changed." in text
    assert "`just check 2>&1 | tail -60` at most twice while working, in addition to the required final run." in text
    assert "Do not run a full `just test` while working." in text
    assert (
        "The only direct pytest invocation permitted is "
        "`uv run --frozen --no-sync python -I -m pytest -q <file> --tb=short | tail -40`, replacing `<file>` with a focused "
        "test file for your change."
    ) in text
    assert "Do not invoke ruff or pyrefly directly, or use another direct pytest command." in text
    assert (
        "After finishing edits and focused verification, run `just check 2>&1 | tail -60` once and then "
        "`just test 2>&1 | tail -40` once, as the last validation before the answer, including an `unchanged` answer."
    ) in text
    assert (
        "Run the final `just test` once in the foreground with sufficient command wait time; never start it in the "
        "background or poll a running `just test`."
    ) in text
    assert "Do not rerun either successful final command." in text
    assert "rerun only the failed command; failure does not justify repeating the successful one." in text
    assert "This failure exception overrides the normal run limits." in text
    assert "`set -o pipefail`" in text and "so `tail` cannot conceal a failed check or test." in text
    assert "Report the underlying command's result, not just `tail`'s status." in text
    assert (
        "These factory instructions take precedence over AGENTS.md's \"Do not run whole-suite/live tests as an agent\" "
        "for the two required final checks, once each, with the stated failure exception."
    ) in text
    assert "This narrow exception does not authorize other whole-suite or live tests." in text
    assert "line length at most 140 (`E501`), at most six returns per function (`PLR0911`)" in text
    assert "no function-local imports (`PLC0415`)" in text
    assert "In `explanation`, name the result of each final command." in text
    assert "run every command" not in text
    assert "at most twice while working" not in task_text(TASK, "plan", CONTEXT)


def test_an_implement_repeat_frames_the_listing_with_its_own_words() -> None:
    found = Unsettled("ignored", ("!! .venv/x",))
    original = task_text(TASK, "implement", CONTEXT)
    text = IMPLEMENT.feedback(found, IMPLEMENT.rules("tl-1"), 2, original, "abcd", unrecorded=True)
    assert text.startswith("These paths are ignored by Git. A listed path Git ignores can never be committed")
    assert "BEGIN SLOT STATUS abcd\n!! .venv/x\nEND SLOT STATUS abcd" in text and "Nothing of attempt 2 was committed" in text
    assert "answer `implemented`" in text and text.endswith(f"The task, for reference:\n\n{original}")
    assert "at most twice while working" in text and "Do not rerun either successful final command." in text
    assert "run `just check 2>&1 | tail -60` once and then `just test 2>&1 | tail -40` once" in text


def test_the_attributes_files_follow_the_step_root_and_the_listed_paths() -> None:
    old = (".gitattributes", "docs/.gitattributes", "docs/design/.gitattributes", "docs/design/tl-1/")
    assert attributes(PLAN.rules("tl-1"), ("docs/design/tl-1/plan.md", "docs/design/tl-1/notes/a.md")) == old
    assert attributes(StepRules(""), ("src/a.py", "README.md")) == (".gitattributes", "src/.gitattributes", "src/a.py", "README.md")


def test_the_plan_input_sends_an_infeasible_or_empty_task_to_needs_owner_at_plan() -> None:
    text = PLAN.input_text(TASK, StepRules("docs/design/tl-1/"), CONTEXT)
    assert "answer `needs_owner`" in text and "write no plan" in text


@pytest.mark.parametrize(("step", "success"), [("plan", "planned"), ("implement", "implemented")])
def test_fixed_input_and_repeat_keep_unfinished_answer_and_saved_work_guidance(step: str, success: str) -> None:
    operation = kind(step)
    text = task_text(TASK, step, CONTEXT)
    guidance = (
        f"Only with `{success}` should `paths` list files; otherwise return `paths: []` and `message: null`, and the factory "
        "saves unfinished slot work as a work-in-progress commit on the task branch when holding the task."
    )
    assert guidance in text and SAVED_WORK in text
    assert f"With `{success}`, remove any other file you created; anything left uncommitted" in text
    assert "ANSWER FORMAT" not in text
    for unrecorded in (False, True):
        repeated = operation.feedback(Unsettled("uncommitted", ("?? new.txt",)), operation.rules("tl-1"), 1,
                                      text, "nonce", unrecorded=unrecorded)
        assert repeated.endswith(text) and guidance in repeated and SAVED_WORK in repeated


def test_failed_check_feedback_keeps_the_fixed_implement_guidance() -> None:
    text = task_text(TASK, "implement", CONTEXT)
    failed = FailedCheck(source=AttemptKey("check", "dispatch", 1), block=1, commit="a" * 40, name="test",
                         argv=("just", "test"), rc=1, output=OutputTail(availability=Availability.EMPTY))
    feedback = failed_check_feedback(failed, text, "nonce")
    assert feedback.endswith(text) and "Only with `implemented` should `paths` list files" in feedback
    assert "the factory saves unfinished slot work" in feedback and SAVED_WORK in feedback
