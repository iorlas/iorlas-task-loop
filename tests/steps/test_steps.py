"""The step kinds: plan then implement, reached through `kind`; their input, repeat framing and attribute files."""

import pytest
from doubles import WORKFLOW

from taskloop.attempt_types import AttemptKey, StepRules, Uncommitted
from taskloop.check_repeat.feedback import Availability, FailedCheck, OutputTail
from taskloop.factory_commit import attributes
from taskloop.input_context import BEGIN, InputContext
from taskloop.plan_reuse import ReuseDecision
from taskloop.resume_plan import Selection
from taskloop.step import Step
from taskloop.step_text import GIT_WRITES, SAVED_WORK
from taskloop.steps import CHECK, IMPLEMENT, KINDS, ORDER, PLAN, failed_check_feedback, following, is_agent, kind, next_step
from taskloop.task import TaskInspection, TaskReference, TaskScope
from taskloop.task_input import task_text

CONTEXT = InputContext("a" * 40, ("just check", "just test"), "Partial glossary: task: Work.\n", ())

TASK = TaskInspection(
    TaskReference(TaskScope("tasks"), "tl-1"), "Add a widget", "It must do X.\nAnd Y.", "- X works\n- Y works", (), "in_progress",
    "taskloop",
)


@pytest.fixture(params=[False, True])
def plan_input(request: pytest.FixtureRequest) -> str:
    text = task_text(TASK, "plan", CONTEXT, WORKFLOW)
    if request.param:
        text = PLAN.feedback(Uncommitted("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    return text


def test_plan_producer_and_feedback_require_committed_preparation_evidence(plan_input: str) -> None:
    for phrase in ("docs/design/tl-1/plan-metadata.json", "include it in `paths`", "`prepared_commit`", "full Source commit",
                   "`cited_paths`", "nonempty array of unique literal repository-relative", "files or folders consulted",
                   "without valid committed metadata needs revision", "retain its metadata and original prepared_commit"):
        assert phrase in plan_input
    repaired = PLAN.feedback(Uncommitted("uncommitted"), PLAN.rules("tl-1"), 1, "short task", "nonce", unrecorded=True)
    assert "plan-metadata.json" in repaired and "`prepared_commit`" in repaired


@pytest.mark.parametrize(("current", "done", "expected"), [
    (None, False, Step.PLAN), (None, True, Step.PLAN), ("plan", True, Step.IMPLEMENT), ("implement", True, CHECK),
    (CHECK, True, None), ("plan", False, None), ("implement", False, None), (CHECK, False, None), ("review", False, None),
])
def test_next_step_follows_the_fixed_order_only_after_a_done_step(current: str | None, done: bool, expected: str | None) -> None:
    """None: a fresh start (or after an abandon returned the claim) is the first step; a done step advances; the last
    built step (`check`) is done; an attempt not done keeps its own `Next`."""
    found = next_step(current, done)
    assert found == expected
    if isinstance(expected, Step):
        assert found is expected


def test_every_step_has_one_kind_and_the_order_is_the_enum_then_check() -> None:
    assert set(KINDS) == set(Step)
    assert all(kind(step) is KINDS[step] and KINDS[step].step is step for step in Step)
    assert tuple(ORDER) == (*Step, CHECK)


def test_the_check_step_follows_implement_and_is_no_agent_kind() -> None:
    """`ORDER` is every built step; only plan and implement have a kind (an agent): `check` is the checks admission's."""
    assert PLAN.step is Step.PLAN and IMPLEMENT.step is Step.IMPLEMENT
    assert kind("plan") is kind(Step.PLAN) is PLAN
    assert kind("implement") is kind(Step.IMPLEMENT) is IMPLEMENT
    assert next_step(Step.PLAN, True) is Step.IMPLEMENT
    assert following("plan") is Step.IMPLEMENT
    assert ORDER == ("plan", "implement", "check") and [following(step) for step in ORDER] == ["implement", "check", None]
    assert [is_agent(step) for step in ORDER] == [True, True, False] and not is_agent("review")
    with pytest.raises(ValueError, match="Unknown step"):
        following("review")
    with pytest.raises(ValueError, match="Unknown step"):
        kind("check")
    with pytest.raises(ValueError, match="Unknown step"):
        kind("review")
    with pytest.raises(ValueError, match="Unknown step"):
        next_step("review", True)


@pytest.mark.parametrize(("decision", "expected"), [
    (ReuseDecision.REUSE, Step.IMPLEMENT), (ReuseDecision.PLAN, Step.PLAN), (ReuseDecision.UNAVAILABLE, Step.PLAN),
])
def test_plan_selection_produces_the_shared_step_member(decision: ReuseDecision, expected: Step) -> None:
    assert Selection(decision, "Selected from the plan evidence.").step is expected


def file_sections(step: Step) -> list[str]:
    """The workflow file's verbatim prose for the step, in file order: owned by the file, never copied into a test."""
    return [section.text for section in WORKFLOW.table(step).prompt if section.text is not None]


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("repeat", [False, True])
def test_the_input_is_the_files_sections_in_order_then_the_contract_at_the_end(step: str, repeat: bool) -> None:
    operation = kind(step)
    text = task_text(TASK, step, CONTEXT, WORKFLOW)
    if repeat:
        text = operation.feedback(Uncommitted("uncommitted"), operation.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    sections = file_sections(operation.step)
    places = [text.index(section) for section in sections]
    assert places == sorted(places) and TASK.title in text and TASK.requirements in text and TASK.acceptance in text
    assert text.index(TASK.title) > places[0] and text.index(BEGIN) < text.rindex(sections[-1]) + len(sections[-1])
    contract = text.rpartition(sections[-1])[2]
    assert "`docs/design/tl-1/plan.md`" in contract and GIT_WRITES in contract
    assert ("Your final message must be the JSON answer only" in text.rstrip().splitlines()[-1]) is (step == "plan")


def test_the_implement_contract_names_the_committed_plan_its_scope_and_the_answer() -> None:
    """The code-owned words after the file's sections: the plan by reference, the path and size caps, Git and the answer."""
    text = task_text(TASK, "implement", CONTEXT, WORKFLOW)
    contract = text.rpartition(file_sections(Step.IMPLEMENT)[-1])[2]
    assert "`docs/design/tl-1/plan.md`, committed on this branch by the plan step." in contract
    assert "at most 96 files of at most 1 MiB each" in contract and GIT_WRITES in contract
    assert "any path starting with `.beads/`, `.task-loop/`, `.task-loop.json`" in contract
    assert SAVED_WORK in contract and text.endswith(SAVED_WORK + "\n")
    assert (
        "In `explanation`, name each command you ran and how it ended, and every test file you added. If you could not finish, "
        "answer `incomplete`; if the plan cannot be implemented as written or needs a decision, answer `needs_owner`; say why "
        "in `explanation`."
    ) in contract



@pytest.mark.parametrize("unrecorded", [True, False])
def test_an_implement_repeat_frames_the_listing_and_preserves_the_complete_input(unrecorded: bool) -> None:
    found = Uncommitted("ignored", ("!! .venv/x",))
    original = task_text(TASK, "implement", CONTEXT, WORKFLOW)
    text = IMPLEMENT.feedback(found, IMPLEMENT.rules("tl-1"), 2, original, "abcd", unrecorded=unrecorded)
    assert text.startswith("These paths are ignored by Git. An ignored attributes file on the way to a changed path")
    assert "BEGIN SLOT STATUS abcd\n!! .venv/x\nEND SLOT STATUS abcd" in text
    assert ("Nothing of attempt 2 was committed" in text) is unrecorded
    assert "answer `implemented`" in text and text.endswith(f"The task, for reference:\n\n{original}")
    assert "read the original content with `git show HEAD:<path>` and restore it with `apply_patch`" in text
    assert "git show HEAD:<path> >" not in text
    assert "at most twice while working" in text and "Do not rerun either successful final command." in text
    assert "run `just check 2>&1 | tail -60` once and then `just test 2>&1 | tail -40` once" in text


@pytest.mark.parametrize("route", ["initial", "repeat", "failed_check"])
def test_implement_allows_latest_shelf_releases_and_stops_for_missing_capabilities(route: str) -> None:
    text = IMPLEMENT.input_text(WORKFLOW.table(IMPLEMENT.step), TASK, IMPLEMENT.rules("tl-1"), CONTEXT)
    if route == "repeat":
        text = IMPLEMENT.feedback(Uncommitted("uncommitted"), IMPLEMENT.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    elif route == "failed_check":
        failed = FailedCheck(source=AttemptKey("check", "dispatch", 1), block=1, commit="a" * 40, name="test",
                             argv=("just", "test"), rc=1, output=OutputTail(availability=Availability.EMPTY))
        text = failed_check_feedback(failed, text, "nonce")
    for phrase in (
        "You may add or upgrade only shelf packages, and only to their most recent released version",
        "Do not add or upgrade any other dependency",
        "task identifiers and task text do not pin versions",
        "acquisition of its latest release is allowed when absent from the prepared cache",
        "Shelf is read-only for agents",
        "If shelf lacks a needed capability, stop with disposition `needs_owner`, `message: null`",
        '`explanation: {"package": "<distribution name>", "capability": "<missing capability>"}`',
        "Use this structured explanation only with `needs_owner`",
        "The owner or supervisor can address the request in the shelf repository",
    ):
        assert phrase in text
    assert "Do not add or upgrade dependencies." not in text


def test_the_attributes_files_follow_the_step_root_and_the_listed_paths() -> None:
    old = (".gitattributes", "docs/.gitattributes", "docs/design/.gitattributes", "docs/design/tl-1/")
    assert attributes(PLAN.rules("tl-1"), ("docs/design/tl-1/plan.md", "docs/design/tl-1/notes/a.md")) == old
    assert attributes(StepRules(""), ("src/a.py", "README.md")) == (".gitattributes", "src/.gitattributes", "src/a.py", "README.md")


def test_the_plan_input_sends_an_infeasible_or_empty_task_to_needs_owner_at_plan() -> None:
    text = PLAN.input_text(WORKFLOW.table(PLAN.step), TASK, StepRules("docs/design/tl-1/"), CONTEXT)
    assert "answer `needs_owner`" in text and "write no plan" in text


def test_implement_contract_does_not_let_the_plan_be_edited() -> None:
    text = task_text(TASK, "implement", CONTEXT, WORKFLOW)
    assert 'Do not edit `plan.md`, including status, progress or "As built" sections' in text
    assert "Other artifacts in the plan's own folder may change under the same rules; add no audit artifact" in text
    assert "Do not change any plan.md, including another task's plan or a deletion" in text
    assert "handoff of what was built belongs in the one-line commit message" in text



@pytest.mark.parametrize(("step", "success"), [("plan", "planned"), ("implement", "implemented")])
def test_fixed_input_and_repeat_keep_unfinished_answer_and_saved_work_guidance(step: str, success: str) -> None:
    operation = kind(step)
    text = task_text(TASK, step, CONTEXT, WORKFLOW)
    condition = (
        f"Only with `{success}` should `paths` list files; otherwise return `paths: []` and `message: null`"
        if step == "plan" else
        "Only with `implemented` should `message` contain a commit message; otherwise return `message: null`"
    )
    guidance = (
        f"{condition}, and the factory "
        "saves unfinished slot work as a work-in-progress commit on the task branch when holding the task."
    )
    assert guidance in text and SAVED_WORK in text
    if step == "plan":
        assert f"With `{success}`, remove any other file you created; anything left uncommitted" in text
        assert "the factory commits exactly those paths" in text
    else:
        assert "The factory derives the commit paths from all tracked and untracked slot changes, including deletions" in text
        assert "Remove unwanted untracked files and restore unwanted tracked edits before answering" in text
        assert "With `implemented`, give a one-line commit `message`" in text
        assert "`paths`" not in text and "paths list" not in text
        assert GIT_WRITES in text
    assert "ANSWER FORMAT" not in text
    for unrecorded in (False, True):
        repeated = operation.feedback(Uncommitted("uncommitted", ("?? new.txt",)), operation.rules("tl-1"), 1,
                                      text, "nonce", unrecorded=unrecorded)
        assert repeated.endswith(text) and guidance in repeated and SAVED_WORK in repeated
        if step == "implement":
            instructions = repeated.removesuffix(text)
            assert "The factory derives the commit paths" in instructions
            assert "Remove unwanted untracked files and restore unwanted tracked edits before answering" in instructions
            assert "`paths`" not in instructions and "paths list" not in instructions
            assert "apply_patch" in instructions


def test_failed_check_feedback_keeps_the_fixed_implement_guidance() -> None:
    text = task_text(TASK, "implement", CONTEXT, WORKFLOW)
    failed = FailedCheck(source=AttemptKey("check", "dispatch", 1), block=1, commit="a" * 40, name="test",
                         argv=("just", "test"), rc=1, output=OutputTail(availability=Availability.EMPTY))
    feedback = failed_check_feedback(failed, text, "nonce")
    assert feedback.endswith(text) and "Only with `implemented` should `message` contain a commit message" in feedback
    assert "`paths`" not in feedback and "paths list" not in feedback
    assert "the factory saves unfinished slot work" in feedback and SAVED_WORK in feedback


def test_plan_change_map_requires_first_line_bullet(plan_input: str) -> None:
    guidance = plan_input.partition("## Change map:")[2].partition("\n")[0]
    assert "the first line under ## Change map must be a bullet" in guidance
    assert "put any explanation inside a bullet" in guidance


@pytest.mark.parametrize("repeat", [False, True])
def test_plan_requests_fixed_lean_template_and_immutable_handoff(repeat: bool) -> None:
    text = PLAN.input_text(WORKFLOW.table(PLAN.step), TASK, PLAN.rules("tl-1"), CONTEXT)
    if repeat:
        text = PLAN.feedback(Uncommitted("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    headings = ("# Header:", "## Outcome and non-goals:", "## Settled decisions:", "## Open decisions:",
                "## Change map:", "## Read list:", "## Contract:", "## Work packages:", "## Acceptance behaviours:")
    assert [text.index(heading) for heading in headings] == sorted(text.index(heading) for heading in headings)
    for phrase in ("300 bytes", "800 bytes", "1,500 bytes", "2,000 bytes", "small 4,000, medium 8,000, large 12,000",
                   "symbol names instead of line numbers", "list every caller found", "producers and callers",
                   "Mark new files as new", "A plan missing this template needs revision, not `unchanged`",
                   "any open decision requires `needs_owner`", "Never grow beyond the cap", "no test names or gate boilerplate",
                   "numbered, with files and the acceptance lines each closes", "intent, effect, result",
                   "cite the task's own decision numbers instead of restating them", "alternatives paragraphs",
                   "restating task text, AGENTS.md or glossary rules", "history or provenance", "tables repeating decisions or code",
                   "Status, As built, Progress or Implementation progress headings and content"):
        assert phrase in text
    assert "## Size" not in text


@pytest.mark.parametrize("repeat", [False, True])
def test_plan_requires_bounded_read_ranges_and_revises_plans_missing_them(repeat: bool) -> None:
    text = PLAN.input_text(WORKFLOW.table(PLAN.step), TASK, PLAN.rules("tl-1"), CONTEXT)
    if repeat:
        text = PLAN.feedback(Uncommitted("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    read_list = text[text.index("## Read list:"):text.index("## Contract:")]
    for phrase in ("nonempty Markdown bullet list of at most 25 entries", "Each entry names an existing file as",
                   "`path:first-last`", "a short reason", "a narrow, useful line range",
                   "Cover every file implementation must edit or consult, including producers and callers",
                   "For new files, mark them as new in the implementation narrative",
                   "list their existing integration points here", "never invent ranges in nonexistent files",
                   "Targeted searches for omitted callers or source that changed after planning are allowed"):
        assert phrase in read_list
    assert "An existing plan missing `## Read list` needs revision before answering `planned` or `unchanged`" in text


def test_plan_read_list_exempts_only_committed_single_target_renames(plan_input: str) -> None:
    read_list = plan_input[plan_input.index("## Read list:"):plan_input.index("## Contract:")]
    assert (
        "Cover every file implementation must edit or consult, including producers and callers. "
        "Exception: a file whose only change is a one-to-one rename listed in a committed naming map is not listed. "
        "Instead, name the map rows and one rg -nw command that must return no matches after implementation. "
        "List the files where the rename touches signatures, logic or behaviour."
    ) in read_list
    assert (
        "Only map rows with one target name qualify; rows whose target depends on a cause stay in normal plan scope."
    ) in read_list
    assert "The rg search returning nothing must be an acceptance line." in read_list
