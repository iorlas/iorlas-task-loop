"""The plan step's own values: its dispositions and their effects, rules and answer contract (schema and decoder), its
input, its repeat instructions and feedback, and the plan.md rule at X. Only `steps` imports this module (an import-linter
contract): the machinery reaches the plan through `steps.kind`. Nothing here runs, reads a store or writes."""

from typing import Final

from git_porcelain import Tree

from taskloop import step_text
from taskloop.attempt_types import (
    MODE,
    Answer,
    Effect,
    PlanContentRule,
    Rejected,
    RepeatReason,
    Rule,
    StepRules,
    Unreadable,
    Unsettled,
    commit_message,
    listed_paths,
    path_allowed,
)
from taskloop.input_context import InputContext
from taskloop.plan_content import PlanDepth, validate
from taskloop.task import TaskInspection

DISPOSITIONS: Final = ("planned", "unchanged", "incomplete", "needs_owner")
# Each disposition's effect, stored with it: only `planned` commits and only `unchanged` keeps B; the rest end nothing.
EFFECT_OF: Final[dict[str, Effect]] = {"planned": "commit", "unchanged": "keep", "incomplete": "none", "needs_owner": "none"}
PLAN_NAME: Final = "plan.md"
FINAL_ANSWER_WARNING: Final = (
    "Your final message must be the JSON answer only; write plan.md before you answer `planned`; "
    "a message without a tool call ends the step."
)
DEPTH_ASSESSMENT: Final = (
    "First assess depth from the supplied task text alone, before any exploration or reading. State the depth in your "
    "first commentary message so the dashboard conversation shows it for owner correction. The only optional cheap "
    "check is at most one search for identifiers named in the task, returning only a count of files and opening nothing. "
    "Do not read source, an existing plan, glossary, tracker or history before this assessment.\n\n"
    "Apply these depth rules in order, using only facts in the task text:\n"
    "- Large: more than 3 independent behaviours, or a schema version change, or an explicitly unlanded task dependency, "
    "or more than 60 named files.\n"
    "- Otherwise medium: 2 to 3 behaviours, or changes in 2 to 3 owning modules.\n"
    "- Otherwise small: one behaviour in one owning module.\n"
    "Three behaviours meet the medium rule; four meet the large rule. 60 named files do not trigger large; 61 do. "
    "A large trigger takes precedence over medium or small. Give a one-sentence reason, state whether an owner decision "
    "is missing or a dependency is unlanded, and state the evidence-gathering budget in model calls: small 6, medium 12, "
    "large 20. These are total evidence ceilings, not additional calls per search or file, and are distinct from the "
    "Size estimate for an implement attempt. Finish within the budget using bounded evidence; a budget alone is not "
    "an owner-refusal cause.\n\n"
    "Before exploring, answer `needs_owner` for exactly these three early causes:\n"
    "- Large work with independent parts: propose a split in words, each part with a name, independently testable "
    "acceptance criterion and dependencies (explicitly none where appropriate).\n"
    "- A missing owner decision: identify the decision and what the owner must resolve.\n"
    "- An explicitly unlanded dependency named in the task: identify the dependency and what must land first.\n"
    "For each early refusal, put `# Depth`, the assessment and concrete reason in `explanation`, within 2000 characters; "
    "write no new plan and offer no commit: use `paths: []`, `message: null`, and the expected or null `plan_path`. "
    "Preserve existing saved work. The owner or orchestrator creates split tasks; do not create them or ask the owner "
    "to run a CLI command. Do not infer a missing decision from terse wording or treat a reference to another task as "
    "proof it is unlanded. A large classification alone is not an early refusal cause. "
    "A single cohesive schema change may be large and still receive a bounded plan when none "
    "of these causes applies. Later refusal for actual contradictions or infeasibility and the separate Size limits "
    "still apply; they are not additional early causes.\n\n"
    "If the assessment permits planning, only then read the existing plan and gather bounded evidence. Within that "
    "evidence budget, inspect existing implementations and supplied overlapping-task information before proposing "
    "remaining work. Use the supplied task discussion; do not require tracker access. Identify what is already "
    "delivered and the remaining gap; avoid duplicating delivered work. Overlap alone establishes neither a missing "
    "owner decision nor an explicitly unlanded dependency. Planning is "
    "never skipped: a small task gets a short plan. Put depth, reason, decision/dependency status, evidence budget and "
    "the Size estimate in Header; do not add separate Depth or Size sections. Reusing an existing plan requires both "
    "current assessments in Header; an existing plan without them needs revision, not `unchanged`. Use the "
    "included glossary excerpt at every depth; collect missing terms into at most one targeted glossary read, after "
    "the assessment permits planning. Depth is plain English: add no glossary term or new stage."
)
ARTIFACT_RULES: Final[tuple[Rule, ...]] = ("plan_missing", "plan_encoding", "plan_empty", "plan_size", *PlanContentRule)
TEMPLATE: Final = (
    "Use exactly these sections in this order, with UTF-8 byte allowances (text after each colon is guidance, "
    "not heading text):\n"
    "# Header: task, base commit, assessment and Size estimate; 300 bytes. The Header must contain one line that is "
    "only `Depth: small|medium|large` (one value, optionally followed by a semicolon and explanation); a Depth "
    "written inside a sentence is refused.\n"
    "## Outcome and non-goals: 800 bytes.\n"
    "## Settled decisions: one line each; a reason only when not obvious; cite the task's own decision numbers "
    "instead of restating them; 1,500 bytes.\n"
    "## Open decisions: list only, never answer them in the plan; any open decision requires `needs_owner`.\n"
    "## Change map: nonempty Markdown bullet list, one line per file, symbol and change; symbol names instead of "
    "line numbers. Find callers in one targeted search and list every caller found, including producers and callers "
    "implementation must consult. Mark new files as new and name their existing integration points; 2,000 bytes or "
    "more as needed within the total cap.\n"
    "## Read list: nonempty Markdown bullet list of at most 25 entries. Each entry names an existing file as "
    "`path:first-last`, with a short reason and a narrow, useful line range. Cover every file implementation must "
    "edit or consult, including producers and callers. For new files, mark them as new in the implementation "
    "narrative and list their existing integration points here; never invent ranges in nonexistent files. "
    "Targeted searches for omitted callers or source that changed after planning are allowed.\n"
    "## Contract: new or changed typed names, states, stored fields and effect boundaries as intent, effect, result; "
    "2,000 bytes or spare space within the total cap.\n"
    "## Work packages: numbered, with files and the acceptance lines each closes.\n"
    "## Acceptance behaviours: one line each, no test names or gate boilerplate; 1,500 bytes.\n"
    "Forbidden in plan.md: restating task text, AGENTS.md or glossary rules; alternatives paragraphs; history or "
    "provenance; tables repeating decisions or code; Status, As built, Progress or Implementation progress headings "
    "and content.\n"
    "Total caps by depth in UTF-8 bytes: "
    + ", ".join(f"{depth.value} {depth.cap:,}" for depth in PlanDepth) + ". Equality passes. "
    "Never grow beyond the cap: remove duplication or answer `needs_owner` with a proposed split, each part with "
    "acceptance and dependencies (explicitly none where appropriate). A plan missing this template needs revision, "
    "not `unchanged`."
)
ANSWER_KEYS: Final = ("disposition", "plan_path", "paths", "message", "explanation")
# The structural answer contract Codex forwards as an OpenAI strict response format: a plain object at the top level (no
# allOf/anyOf/oneOf/not/enum/if there), every property required, nullable by type list, no composition keywords at all.
# `paths` and `message` are what the agent asks the factory to commit; the agent never commits. Every bound and every
# cross-field rule (planned needs the expected path, the listed paths and a message) belong to `decode` alone.
ANSWER_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": list(ANSWER_KEYS),
    "properties": {
        "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
        "plan_path": {"type": ["string", "null"]},
        "paths": {"type": "array", "items": {"type": "string"}},
        "message": {"type": ["string", "null"]},
        "explanation": {"type": "string"},
    },
}
OPENING: Final[dict[RepeatReason, str]] = {
    "uncommitted": "Attempt {number} of this step left changes in the slot that it did not list for commit.",
    "unsafe": "These paths cannot be committed.",
    "ignored": "These paths are ignored by Git. Any ignored file under the plan folder, and any ignored attributes file, "
    "blocks the commit whether it is listed or not; a listed one can never be committed.",
}


def step_rules(task_id: str) -> StepRules:
    """The plan step's rules: its files live under `docs/design/<task-id>/`, the plan itself is `plan.md` there."""
    return StepRules(f"docs/design/{task_id}/")


def decode(value: object, rules: StepRules) -> Answer:
    """Validate the factory's plan answer contract, without verifying Git effects; the single owner of its cross-field
    rules and every bound (the strict schema carries none). Unfinished answers ignore structurally valid paths without
    requesting a commit. The expected plan is `<rules.root>plan.md`."""
    if not isinstance(value, dict) or set(value) != set(ANSWER_KEYS):
        raise ValueError("Invalid plan answer")
    disposition, path, paths, message, explanation = (value[key] for key in ANSWER_KEYS)
    expected = rules.root + PLAN_NAME
    if disposition in ("incomplete", "needs_owner"):
        listed = () if isinstance(paths, list) and all(isinstance(path, str) for path in paths) else None
    else:
        listed = listed_paths(paths, rules)
    if disposition == "planned":
        fits = path == expected and listed is not None and expected in listed and commit_message(message)
    else:
        named = path == expected or path is None  # `unchanged` without a plan decodes: verification names `plan_missing`
        fits = disposition in DISPOSITIONS and named and listed == () and message is None
    if not fits or listed is None or not isinstance(explanation, str) or len(explanation) > 2000:
        raise ValueError("Invalid plan answer")
    text = message if isinstance(message, str) else None
    return Answer(str(disposition), EFFECT_OF[str(disposition)], listed, text, explanation)


def input_text(task: TaskInspection, rules: StepRules, context: InputContext) -> str:
    """Put the depth assessment before task prose, orientation and plan reads; the factory commits listed paths."""
    return (f"{FINAL_ANSWER_WARNING}\n\n{DEPTH_ASSESSMENT}\n\n"
            f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}\n\n{context.render()}\n\n"
            f"{_closing_words(rules)}\n")


def _closing_words(rules: StepRules) -> str:
    root = rules.root
    return (
        "After the depth assessment permits planning, follow this plan-only reading order. These rules supersede "
        "the shared foundation-read condition:\n"
        "1. AGENTS.md rules are already in context; follow them without reopening the file.\n"
        "2. Use the supplied glossary excerpt; collect missing terms into at most one targeted read of "
        "`docs/glossary.md`. If no glossary exists at the source commit, do not search for one.\n"
        f"3. After the depth assessment permits planning, read `{root}{PLAN_NAME}` if it exists.\n"
        "4. Read a foundation plan only when the task text names it.\n"
        "For this list, read each of these once; never read a file twice. Then gather only the source evidence "
        "needed for the task.\n\n"
        "Search with an explicit repository path scope and a count first (`rg -c`) before printing matching lines. "
        "Do not search outside the repository, including task-loop state, ~/.codex or the uv cache. "
        "An output marked truncated means the search was too wide: narrow the scope or range; do not repeat "
        "the same command or increase the output limit. "
        "For shelf facts, use the supplied shelf digest from .186; do not discover an installed shelf package "
        "outside the repository or invent missing digest contents. If a necessary shelf fact is absent, answer "
        "`needs_owner` and explain the missing fact in words.\n\n"
        f"{TEMPLATE}\n\nBefore answering `planned` or `unchanged`, require a Size estimate in Header with "
        "estimated changed files (including tests and artifacts), independent behaviours, and model calls "
        "for one implement attempt. Each independent behaviour must have an independently testable acceptance criterion; "
        "file count alone is insufficient. An existing plan without this assessment needs revision, not `unchanged`. "
        "An existing plan missing `## Read list` needs revision before answering `planned` or `unchanged`. "
        "Reassess the existing Header Size estimate against the current requirements and code before reusing it. "
        "If any estimate exceeds 60 files, 3 independent behaviours or 100 model calls, answer `needs_owner`, never "
        "`planned` or `unchanged`. Equality is allowed (60 files, 3 behaviours, 100 calls); 61 files, 4 behaviours or "
        "101 calls each suffice for refusal. Low file count cannot excuse another excess. Put the reason and proposed "
        "split in `explanation`, within its existing 2000-character limit: each part must have a name, acceptance criterion "
        "and dependencies (explicitly none where appropriate). The owner or orchestrator creates the parts in the task "
        "tracker; do not create them or ask the owner to run a CLI command. On refusal, write no new successful plan and "
        "offer no commit: use `paths: []`, `message: null`, and the expected or null `plan_path`. Preserve existing saved "
        "work; a draft is not approval to implement. If the assessed plan is still valid for the task and code as they "
        "are now, change nothing and answer `unchanged`. Otherwise write the plan there (rewrite it in place if it exists) and answer "
        f"`planned`; other files only under `{root}`. {step_text.GIT_WRITES} With `planned`, list in `paths` every file "
        "you want committed and give a "
        "one-line commit `message`; the factory commits exactly those paths. With `planned`, remove any other file you "
        "created; anything left uncommitted is reported back to you as a failed step. If the task cannot be planned as "
        "written (it contradicts "
        "itself or the code, is empty or too vague to act on), write no plan: answer `needs_owner` and say in `explanation` "
        "what the owner must decide. If you could not finish planning, answer `incomplete` and explain why in "
        "`explanation`. Only with `planned` should `paths` list files; otherwise return `paths: []` and "
        "`message: null`, and the factory saves unfinished slot work as a work-in-progress commit on the task branch "
        "when holding the task. " + step_text.SAVED_WORK
    )


def repeat_instructions(rules: StepRules, number: int, *, unrecorded: bool) -> str:
    """A repeat's fixed instructions for the plan step. `unrecorded`: attempt `number` answered `planned` and nothing of
    it was committed, so its files must be listed again."""
    root, plan = rules.root, rules.root + PLAN_NAME
    last = (
        f"Nothing of attempt {number} was committed: answer `planned` and list in `paths` "
        f"again every file you want committed, `{plan}` included."
        if unrecorded
        else "If you only removed or restored files, answer `unchanged`: a `planned` answer with nothing new to commit is "
        "rejected for good."
    )
    return (
        f"Remove every untracked file listed that does not belong to the plan. A tracked file you changed outside `{root}` "
        "cannot be committed: restore its committed content (`git show HEAD:<path> > <path>`); you cannot run `git checkout` "
        f"or `git restore`. With `planned`, `paths` always lists `{plan}` and every other file under that folder you want "
        f"kept, and only when you changed or added a file there; leave files you did not change out of paths. {last}"
    )


def feedback(found: Unsettled, rules: StepRules, number: int, task: str, nonce: str, *, unrecorded: bool) -> str:
    """The next input: warning and assessment before the shared feedback frame, listing, repair instructions and task.
    `unrecorded`: attempt `number` answered `planned` and
    nothing of it was committed, so its files must be listed again. `found.reason` is one of REPEATABLE."""
    opening = next(text for reason, text in OPENING.items() if reason == found.reason)
    instructions = repeat_instructions(rules, number, unrecorded=unrecorded)
    opening = step_text.unsafe_details(found) or opening.format(number=number)
    return (FINAL_ANSWER_WARNING + "\n\n" + DEPTH_ASSESSMENT + "\n\n"
            + step_text.feedback(opening, found.listing, instructions, task, nonce))


def artifact(tip: Tree, rules: StepRules) -> Rejected | str:
    """The plan at X passes the path and mode rules and the content floor, giving its blob; never a review of what it
    says."""
    plan_path = rules.root + PLAN_NAME
    if not path_allowed(plan_path, rules):
        return Rejected("paths")
    entry = tip.files.get(plan_path)
    if entry is None:
        return Rejected("plan_missing")
    if entry[0] != MODE:
        return Rejected("mode")
    data = tip.read(plan_path)
    if data is None:  # the listing has the plan: an empty read is a failed read
        raise Unreadable("blob")
    broken = _content(data, rules.file_cap)
    return entry[1] if broken is None else Rejected(broken)


def _content(data: bytes, cap: int) -> Rule | None:
    """Strict UTF-8, not whitespace only, at most `cap` bytes after the full read."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "plan_encoding"
    if not text.strip():
        return "plan_empty"
    if len(data) > cap:
        return "plan_size"
    return validate(text, len(data))
