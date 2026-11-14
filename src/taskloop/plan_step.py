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
from taskloop.task import TaskInspection

DISPOSITIONS: Final = ("planned", "unchanged", "incomplete", "needs_owner")
# Each disposition's effect, stored with it: only `planned` commits and only `unchanged` keeps B; the rest end nothing.
EFFECT_OF: Final[dict[str, Effect]] = {"planned": "commit", "unchanged": "keep", "incomplete": "none", "needs_owner": "none"}
PLAN_NAME: Final = "plan.md"
ARTIFACT_RULES: Final[tuple[Rule, ...]] = ("plan_missing", "plan_encoding", "plan_empty", "plan_size")  # the plan.md rule's words
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
    "unsafe": "This listed path, or a `.git*` file near it, cannot be committed: a symlink or under one, not a plain file, "
    "executable, over 1 MiB, or a Git file.",
    "ignored": "These paths are ignored by Git. Any ignored file under the plan folder, and any ignored attributes file, "
    "blocks the commit whether it is listed or not; a listed one can never be committed.",
}


def step_rules(task_id: str) -> StepRules:
    """The plan step's rules: its files live under `docs/design/<task-id>/`, the plan itself is `plan.md` there."""
    return StepRules(f"docs/design/{task_id}/")


def decode(value: object, rules: StepRules) -> Answer:
    """Validate the factory's plan answer contract, without verifying Git effects; the single owner of its cross-field
    rules and every bound (the strict schema carries none). The expected plan is `<rules.root>plan.md`."""
    if not isinstance(value, dict) or set(value) != set(ANSWER_KEYS):
        raise ValueError("Invalid plan answer")
    disposition, path, paths, message, explanation = (value[key] for key in ANSWER_KEYS)
    expected, listed = rules.root + PLAN_NAME, listed_paths(paths, rules)
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
    """The plan step's admitted input: the task's own prose, then the fixed closing words (where the plan goes,
    `unchanged` or `planned`, no Git write: the factory commits the listed paths)."""
    return (f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}\n\n{context.render()}\n\n"
            f"{_closing_words(rules)}\n")


def _closing_words(rules: StepRules) -> str:
    root = rules.root
    return (
        f"First read `{root}{PLAN_NAME}` if it exists. If it is still valid for the task and the code as they are now, change "
        f"nothing and answer `unchanged`. Otherwise write the plan there (rewrite it in place if it exists) and answer "
        f"`planned`; other files only under `{root}`. {step_text.GIT_WRITES} With `planned`, list in `paths` every file "
        "you want committed and give a "
        "one-line commit `message`; the factory commits exactly those paths. Remove any other file you created. Anything "
        "left uncommitted is reported back to you as a failed step. If the task cannot be planned as written (it contradicts "
        "itself or the code, is empty or too vague to act on), write no plan: answer `needs_owner` and say in `explanation` "
        "what the owner must decide. " + step_text.SAVED_WORK
    )


def repeat_instructions(rules: StepRules, number: int, *, unrecorded: bool) -> str:
    """A repeat's fixed instructions for the plan step. `unrecorded`: attempt `number` answered `planned` and nothing of
    it was committed, so its files must be listed again."""
    root, plan = rules.root, rules.root + PLAN_NAME
    last = (
        f"Nothing of attempt {number} was committed, so none of its files is in Git: answer `planned` and list in `paths` "
        f"again every file you want committed, `{plan}` included."
        if unrecorded
        else "If you only removed or restored files, answer `unchanged`: a `planned` answer with nothing new to commit is "
        "rejected for good."
    )
    return (
        f"Remove every untracked file listed that does not belong to the plan. A tracked file you changed outside `{root}` "
        "cannot be committed: restore its committed content (`git show HEAD:<path> > <path>`); you cannot run `git checkout` "
        f"or `git restore`. With `planned`, `paths` always lists `{plan}` and every other file under that folder you want "
        f"kept, and only when you changed or added a file there. {last}"
    )


def feedback(found: Unsettled, rules: StepRules, number: int, task: str, nonce: str, *, unrecorded: bool) -> str:
    """The next attempt's complete input in the shared frame (`step_text.feedback`): the plan's fixed words for the
    reason, the listing, its fixed instructions, then the task. `unrecorded`: attempt `number` answered `planned` and
    nothing of it was committed, so its files must be listed again. `found.reason` is one of REPEATABLE."""
    opening = next(text for reason, text in OPENING.items() if reason == found.reason)
    instructions = repeat_instructions(rules, number, unrecorded=unrecorded)
    return step_text.feedback(opening.format(number=number), found.listing, instructions, task, nonce)


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
    return "plan_size" if len(data) > cap else None
