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

CONTEXT = InputContext("a" * 40, ("just check", "just test"), "Partial glossary: task: Work.\n", ())

TASK = TaskInspection(
    TaskReference(TaskScope("tasks"), "tl-1"), "Add a widget", "It must do X.\nAnd Y.", "- X works\n- Y works", (), "in_progress",
    "taskloop",
)


@pytest.fixture(params=[False, True])
def plan_input(request: pytest.FixtureRequest) -> str:
    text = task_text(TASK, "plan", CONTEXT)
    if request.param:
        text = PLAN.feedback(Unsettled("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    return text


def test_plan_producer_and_feedback_require_committed_preparation_evidence(plan_input: str) -> None:
    for phrase in ("docs/design/tl-1/plan-metadata.json", "include it in `paths`", "`prepared_commit`", "full Source commit",
                   "`cited_paths`", "nonempty array of unique literal repository-relative", "files or folders consulted",
                   "without valid committed metadata needs revision", "retain its metadata and original prepared_commit"):
        assert phrase in plan_input
    repaired = PLAN.feedback(Unsettled("uncommitted"), PLAN.rules("tl-1"), 1, "short task", "nonce", unrecorded=True)
    assert "plan-metadata.json" in repaired and "`prepared_commit`" in repaired


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
    prepared: uv offline after setup, `$TMPDIR`, and that only the checks run afterwards count."""
    text = task_text(TASK, "implement", CONTEXT)
    assert text.startswith("Add a widget\n\nIt must do X.\nAnd Y.\n\n- X works\n- Y works\n\n")
    assert "`docs/design/tl-1/plan.md`, committed on this branch by the plan step." in text
    assert "at most 96 files of at most 1 MiB each" in text and "anything under `.beads/`" in text and GIT_WRITES in text
    assert "The factory ran this repository's `setup` before you started; uv uses the prepared cache offline." in text
    assert "there is no network now" not in text
    assert "Temporary files go to `$TMPDIR`; cleanup is attempted after release and required before the next agent." in text
    assert "Do not write elsewhere outside the repository." in text
    assert "Your runs are evidence for you: after this step the checks run again outside your control, " in text
    assert "only those results count. " in text
    assert "retain heredoc edits with the bounded verification above. With `implemented`" in text
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
    assert "Make every file edit with `apply_patch`, never with a Python or sed script" in text
    assert "additions, deletions and repairs" in text and "do not rewrite repository files with shell redirection" in text
    assert "The project interpreter is `.venv/bin/python`" in text
    assert "`uv run --frozen --no-sync python -I` for execution or inspection scripts, never for file edits" in text
    assert "Bare `python3` is the host's Python 3.12, not the project's Python 3.15" in text
    assert "First confirm that `apply_patch` is offered in your implement tool set" in text
    assert "Only if `apply_patch` is absent, report the tool gap in `explanation` only" in text
    assert "retain heredoc edits with the bounded verification above" in text
    assert "at most twice while working" not in task_text(TASK, "plan", CONTEXT)


@pytest.mark.parametrize("unrecorded", [True, False])
def test_an_implement_repeat_frames_the_listing_and_preserves_the_complete_input(unrecorded: bool) -> None:
    found = Unsettled("ignored", ("!! .venv/x",))
    original = task_text(TASK, "implement", CONTEXT)
    text = IMPLEMENT.feedback(found, IMPLEMENT.rules("tl-1"), 2, original, "abcd", unrecorded=unrecorded)
    assert text.startswith("These paths are ignored by Git. A listed path Git ignores can never be committed")
    assert "BEGIN SLOT STATUS abcd\n!! .venv/x\nEND SLOT STATUS abcd" in text
    assert ("Nothing of attempt 2 was committed" in text) is unrecorded
    assert "answer `implemented`" in text and text.endswith(f"The task, for reference:\n\n{original}")
    assert "read the original content with `git show HEAD:<path>` and restore it with `apply_patch`" in text
    assert "git show HEAD:<path> >" not in text
    assert "at most twice while working" in text and "Do not rerun either successful final command." in text
    assert "run `just check 2>&1 | tail -60` once and then `just test 2>&1 | tail -40` once" in text


def test_the_attributes_files_follow_the_step_root_and_the_listed_paths() -> None:
    old = (".gitattributes", "docs/.gitattributes", "docs/design/.gitattributes", "docs/design/tl-1/")
    assert attributes(PLAN.rules("tl-1"), ("docs/design/tl-1/plan.md", "docs/design/tl-1/notes/a.md")) == old
    assert attributes(StepRules(""), ("src/a.py", "README.md")) == (".gitattributes", "src/.gitattributes", "src/a.py", "README.md")


def test_the_plan_input_sends_an_infeasible_or_empty_task_to_needs_owner_at_plan() -> None:
    text = PLAN.input_text(TASK, StepRules("docs/design/tl-1/"), CONTEXT)
    assert "answer `needs_owner`" in text and "write no plan" in text


@pytest.mark.parametrize(("depth", "rule"), [
    ("Large", "more than 3 independent behaviours"),
    ("Large", "a schema version change"),
    ("Large", "an explicitly unlanded task dependency"),
    ("Large", "more than 60 named files"),
    ("Otherwise medium", "2 to 3 behaviours"),
    ("Otherwise medium", "changes in 2 to 3 owning modules"),
    ("Otherwise small", "one behaviour in one owning module"),
])
def test_plan_depth_rules_are_explicit_and_precede_exploration(plan_input: str, depth: str, rule: str) -> None:
    text = plan_input.partition("BEGIN SLOT STATUS nonce")[0]
    assessment = text.split("Apply these depth rules in order, using only facts in the task text:")[1].split("\n\n")[0]
    assert rule in assessment.split(f"- {depth}: ")[1].split("\n")[0]
    assert "Three behaviours meet the medium rule; four meet the large rule" in assessment
    assert "60 named files do not trigger large; 61 do" in assessment
    assert "A large trigger takes precedence over medium or small" in assessment


@pytest.mark.parametrize(("depth", "calls"), [("small", 6), ("medium", 12), ("large", 20)])
def test_plan_evidence_budgets_bound_total_evidence_not_implementation_estimates(plan_input: str, depth: str, calls: int) -> None:
    text = plan_input.partition("BEGIN SLOT STATUS nonce")[0]
    assert f"{depth} {calls}" in text.split("evidence-gathering budget in model calls: ")[1].split(".")[0]
    assert "total evidence ceilings, not additional calls per search or file" in text
    assert "distinct from the Size estimate for an implement attempt" in text
    assert "Finish within the budget using bounded evidence; a budget alone is not an owner-refusal cause" in text


def test_plan_assessment_precedes_task_orientation_and_reads_and_is_visible_and_persisted(plan_input: str) -> None:
    text = plan_input
    assessment = text.index("First assess depth from the supplied task text alone")
    task, orientation = text.index(TASK.title), text.index("AGENTS.md is already in context")
    plan_read = text.index("After the depth assessment permits planning, read `docs/design/tl-1/plan.md`")
    assert text.startswith("Your final message must be the JSON answer only;")
    assert assessment < text.index("Do not read source, an existing plan, glossary, tracker or history") < task
    assert assessment < task < orientation < plan_read
    if "BEGIN SLOT STATUS nonce" in text:
        assert assessment < text.index("BEGIN SLOT STATUS nonce") < text.index("Remove every untracked file listed") < task
        assert text.index("Depth is plain English: add no glossary term or new stage") < text.index("BEGIN SLOT STATUS nonce")
    assert "first commentary message so the dashboard conversation shows it for owner correction" in text
    assert "The only optional cheap check is at most one search for identifiers named in the task" in text
    assert "returning only a count of files and opening nothing" in text
    assert "only then read the existing plan and gather bounded evidence" in text
    assert "Planning is never skipped: a small task gets a short plan" in text
    assert "Put depth, reason, decision/dependency status, evidence budget and the Size estimate in Header" in text
    assert "do not add separate Depth or Size sections" in text
    assert "current assessments in Header; an existing plan without them needs revision, not `unchanged`" in text
    assert "Use the included glossary excerpt at every depth" in text
    assert "collect missing terms into at most one targeted glossary read, after the assessment permits planning" in text
    assert "Depth is plain English: add no glossary term or new stage" in text


@pytest.mark.parametrize(("cause", "explanation"), [
    ("Large work with independent parts", "each part with a name, independently testable acceptance criterion and dependencies"),
    ("A missing owner decision", "identify the decision and what the owner must resolve"),
    ("An explicitly unlanded dependency named in the task", "identify the dependency and what must land first"),
])
def test_plan_early_refusals_name_the_cause_in_words_without_artifacts(plan_input: str, cause: str, explanation: str) -> None:
    text = plan_input.partition("BEGIN SLOT STATUS nonce")[0]
    early = text.split("Before exploring, answer `needs_owner` for exactly these three early causes:")[1].split("\n\n")[0]
    assert len([line for line in early.splitlines() if line.startswith("- ")]) == 3
    assert f"- {cause}: " in early and explanation in early
    assert "explicitly none where appropriate" in early
    assert "put `# Depth`, the assessment and concrete reason in `explanation`, within 2000 characters" in early
    assert "write no new plan and offer no commit" in early
    assert "`paths: []`, `message: null`, and the expected or null `plan_path`" in early
    assert "Preserve existing saved work" in early
    assert "The owner or orchestrator creates split tasks; do not create them" in early
    assert "Do not infer a missing decision from terse wording" in early
    assert "or treat a reference to another task as proof it is unlanded" in early
    assert "A large classification alone is not an early refusal cause" in early
    assert "A single cohesive schema change may be large and still receive a bounded plan" in early
    assert "Later refusal for actual contradictions or infeasibility and the separate Size limits still apply" in early
    assert "write plan.md before you answer `planned`" in text


def test_plan_inspects_existing_work_and_supplied_overlap_only_after_assessment_permits_planning(plan_input: str) -> None:
    permitted = plan_input.index("If the assessment permits planning")
    inspection = plan_input.index("Within that evidence budget, inspect existing implementations")
    assert plan_input.index("Before exploring, answer `needs_owner`") < permitted < inspection < plan_input.index(TASK.title)
    text = plan_input.partition("BEGIN SLOT STATUS nonce")[0]
    assert "supplied overlapping-task information before proposing remaining work" in text
    assert "Use the supplied task discussion; do not require tracker access" in text
    assert "Identify what is already delivered and the remaining gap; avoid duplicating delivered work" in text
    assert "Overlap alone establishes neither a missing owner decision nor an explicitly unlanded dependency" in text


def test_plan_success_requires_a_current_size_assessment_and_an_owner_created_split_on_refusal() -> None:
    text = task_text(TASK, "plan", CONTEXT)
    assert "Before answering `planned` or `unchanged`, require a Size estimate in Header" in text
    assert "estimated changed files (including tests and artifacts), independent behaviours, and model calls" in text
    assert "for one implement attempt" in text
    assert "Each independent behaviour must have an independently testable acceptance criterion" in text
    assert "file count alone is insufficient" in text
    assert "An existing plan without this assessment needs revision, not `unchanged`" in text
    assert "Reassess the existing Header Size estimate against the current requirements and code before reusing it" in text
    assert "reason and proposed split in `explanation`, within its existing 2000-character limit" in text
    assert "each part must have a name, acceptance criterion and dependencies (explicitly none where appropriate)" in text
    assert "The owner or orchestrator creates the parts in the task tracker; do not create them" in text
    assert "or ask the owner to run a CLI command" in text
    assert "On refusal, write no new successful plan and offer no commit" in text
    assert "use `paths: []`, `message: null`, and the expected or null `plan_path`" in text
    assert "Preserve existing saved work; a draft is not approval to implement" in text


@pytest.mark.parametrize("excess", ["61 files", "4 behaviours", "101 calls"])
def test_plan_limits_allow_equality_and_refuse_each_independent_excess(excess: str) -> None:
    text = task_text(TASK, "plan", CONTEXT)
    assert (
        "If any estimate exceeds 60 files, 3 independent behaviours or 100 model calls, answer `needs_owner`, never "
        "`planned` or `unchanged`."
    ) in text
    assert "Equality is allowed (60 files, 3 behaviours, 100 calls)" in text
    assert excess in text.split("each suffice for refusal")[0].split("Equality is allowed")[1]
    assert "Low file count cannot excuse another excess" in text


def test_implement_reassesses_before_exploration_and_stops_with_unfinished_work_without_editing_the_plan() -> None:
    text = task_text(TASK, "implement", CONTEXT)
    assert "Read it first. Immediately after reading the plan, reassess scope before broad exploration or editing" in text
    assert "more than about 60 model calls or touches more than 60 files" in text
    assert "stop after the first coherent part, commit nothing extra, and answer `needs_owner` with the proposed split" in text
    assert "If the excess is evident before editing, answer then; do not begin a part just to have something to save" in text
    assert "stop at the first coherent boundary without proceeding into another work package" in text
    assert "Explain completed and remaining scope and propose named parts" in text
    assert "each with an acceptance criterion and dependencies (explicitly none where appropriate)" in text
    assert "Partial work is unfinished: use `needs_owner`, `paths: []`, `message: null`; the hold saves it" in text
    assert "The owner or orchestrator creates parts in the task tracker; do not create them" in text
    assert "or ask the owner to run a CLI command" in text
    assert "100 estimated model calls limit is distinct from this implement reassessment at about 60 calls" in text
    assert "scope instructions, not harness call quotas" in text
    assert "60-file stop is earlier than the existing 96-path safety ceiling" in text
    assert 'Do not edit `plan.md`, including status, progress or "As built" sections' in text
    assert "Other artifacts in the plan's own folder may change under the same rules; add no audit artifact" in text
    assert "tool gap in the plan" not in text


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


@pytest.mark.parametrize("repeat", [False, True])
def test_plan_orientation_bounds_reads_searches_and_truncated_output(repeat: bool) -> None:
    text = PLAN.input_text(TASK, PLAN.rules("tl-1"), CONTEXT)
    if repeat:
        text = PLAN.feedback(Unsettled("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    ordered = (
        "1. AGENTS.md rules are already in context; follow them without reopening the file.",
        "2. Use the supplied glossary excerpt; collect missing terms into at most one targeted read of `docs/glossary.md`.",
        "3. After the depth assessment permits planning, read `docs/design/tl-1/plan.md` if it exists.",
        "4. Read a foundation plan only when the task text names it.",
    )
    positions = [text.index(phrase) for phrase in ordered]
    assert positions == sorted(positions)
    assert text.index("END FACTORY INPUT CONTEXT") < positions[0]
    for phrase in (*ordered,
                   "These rules supersede the shared foundation-read condition:",
                   "read each of these once; never read a file twice",
                   "Search with an explicit repository path scope and a count first (`rg -c`) before printing matching lines.",
                   "Do not search outside the repository, including task-loop state, ~/.codex or the uv cache.",
                   "An output marked truncated means the search was too wide: narrow the scope or range; do not repeat "
                   "the same command or increase the output limit.",
                   "For shelf facts, use the supplied shelf digest from .186",
                   "If a necessary shelf fact is absent, answer `needs_owner` and explain the missing fact in words."):
        assert text.count(phrase) == 1
        assert phrase not in IMPLEMENT.input_text(TASK, IMPLEMENT.rules("tl-1"), CONTEXT)
    assert "You have no task tracker" not in text
    assert "bd and the beads skill are unavailable" not in text


@pytest.mark.parametrize("repeat", [False, True])
def test_plan_requests_fixed_lean_template_and_immutable_handoff(repeat: bool) -> None:
    text = PLAN.input_text(TASK, PLAN.rules("tl-1"), CONTEXT)
    if repeat:
        text = PLAN.feedback(Unsettled("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
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
    text = PLAN.input_text(TASK, PLAN.rules("tl-1"), CONTEXT)
    if repeat:
        text = PLAN.feedback(Unsettled("uncommitted"), PLAN.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    read_list = text[text.index("## Read list:"):text.index("## Contract:")]
    for phrase in ("nonempty Markdown bullet list of at most 25 entries", "Each entry names an existing file as",
                   "`path:first-last`", "a short reason", "a narrow, useful line range",
                   "Cover every file implementation must edit or consult, including producers and callers",
                   "For new files, mark them as new in the implementation narrative",
                   "list their existing integration points here", "never invent ranges in nonexistent files",
                   "Targeted searches for omitted callers or source that changed after planning are allowed"):
        assert phrase in read_list
    assert "An existing plan missing `## Read list` needs revision before answering `planned` or `unchanged`" in text


@pytest.mark.parametrize("route", ["initial", "repeat", "failed_check"])
def test_implement_reading_directions_survive_both_retry_routes(route: str) -> None:
    text = IMPLEMENT.input_text(TASK, IMPLEMENT.rules("tl-1"), CONTEXT)
    if route == "repeat":
        text = IMPLEMENT.feedback(Unsettled("uncommitted", ("?? stray",)), IMPLEMENT.rules("tl-1"), 2,
                                  text, "nonce", unrecorded=False)
    elif route == "failed_check":
        failed = FailedCheck(source=AttemptKey("check", "dispatch", 1), block=1, commit="a" * 40, name="test",
                             argv=("just", "test"), rc=1, output=OutputTail(availability=Availability.EMPTY))
        text = failed_check_feedback(failed, text, "nonce")
    for phrase in ("Read its `## Read list` by the stated line ranges before exploring other files", "Search with `rg -n`",
                   "targeted searches for omitted callers or source that changed after planning are allowed",
                   "Do not `cat` a file over 300 lines", "file over 150 lines",
                   "`rg -n '^def |^class '`", "even if the symbol search is empty", "Do not batch whole-file dumps",
                   "Do not read a file again within this session unless it changed", "read only the changed range",
                   "including verification after an edit", "edit without reopening unchanged content",
                   "Do not edit plan.md", "paths list must not contain any plan.md", "including another task's plan or a deletion",
                   "handoff of what was built belongs in the one-line commit message"):
        assert phrase in text
