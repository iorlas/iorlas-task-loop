"""The implement step's own values: its dispositions and their effects, rules and answer contract (schema and decoder),
its input, its repeat instructions and feedback. It has no artifact: verified means the generic chain rules and the clean
tree, never "the code works" (the factory's own checks decide that). Only `steps` imports this module (an import-linter
contract). Nothing here runs, reads a store or writes."""

from typing import Final

from git_porcelain import Tree

from taskloop import step_text
from taskloop.attempt_types import (
    Answer,
    Effect,
    MiB,
    RepeatReason,
    Rule,
    StepRules,
    Unsettled,
    commit_message,
    listed_paths,
)
from taskloop.task import TaskInspection

DISPOSITIONS: Final = ("implemented", "unchanged", "incomplete", "needs_owner")
# Each disposition's effect, stored with it: only `implemented` commits and only `unchanged` keeps B.
EFFECT_OF: Final[dict[str, Effect]] = {"implemented": "commit", "unchanged": "keep", "incomplete": "none", "needs_owner": "none"}
ARTIFACT_RULES: Final[tuple[Rule, ...]] = ()  # no artifact rule at X
EXCLUDED: Final = (".beads/",)  # the tracker's files: never the agent's to commit
ANSWER_KEYS: Final = ("disposition", "paths", "message", "explanation")
# The plan's strict-format pattern without `plan_path`: what the agent ran is reported in `explanation` only.
ANSWER_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": list(ANSWER_KEYS),
    "properties": {
        "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
        "paths": {"type": "array", "items": {"type": "string"}},
        "message": {"type": ["string", "null"]},
        "explanation": {"type": "string"},
    },
}
OPENING: Final[dict[RepeatReason, str]] = {
    "uncommitted": "Attempt {number} of this step left changes in the slot that it did not list for commit.",
    "unsafe": "This listed path, or a `.git*` file near it, cannot be committed: a symlink or under one, not a plain file, "
    "executable, over 1 MiB, or a Git file.",
    "ignored": "These paths are ignored by Git. A listed path Git ignores can never be committed, and an ignored attributes "
    "file on the way to a listed path blocks the commit.",
}


def step_rules(_task_id: str) -> StepRules:
    """The whole repository, deletions included, except the tracker's files; the plan it follows is
    `docs/design/<task-id>/plan.md`."""
    return StepRules("", max_paths=96, deletions=True, excluded=EXCLUDED)


def decode(value: object, rules: StepRules) -> Answer:
    """Validate the implement answer contract, without verifying Git effects; the single owner of its cross-field rules
    and every bound: `implemented` lists at least one path and a message, every other disposition lists none."""
    if not isinstance(value, dict) or set(value) != set(ANSWER_KEYS):
        raise ValueError("Invalid implement answer")
    disposition, paths, message, explanation = (value[key] for key in ANSWER_KEYS)
    listed = listed_paths(paths, rules)
    if disposition == "implemented":
        fits = bool(listed) and commit_message(message)
    else:
        fits = disposition in DISPOSITIONS and listed == () and message is None
    if not fits or listed is None or not isinstance(explanation, str) or len(explanation) > 2000:
        raise ValueError("Invalid implement answer")
    text = message if isinstance(message, str) else None
    return Answer(str(disposition), EFFECT_OF[str(disposition)], listed, text, explanation)


def input_text(task: TaskInspection, rules: StepRules) -> str:
    """The implement step's admitted input: the task's own prose, then the fixed closing words. The plan is passed by
    reference: the slot starts on `task/<id>` at the published plan commit."""
    return f"{task.title}\n\n{task.requirements}\n\n{task.acceptance}\n\n{_closing_words(task.reference.task_id, rules)}\n"


def _closing_words(task_id: str, rules: StepRules) -> str:
    return (
        f"The plan for this task is `docs/design/{task_id}/plan.md`, committed on this branch by the plan step. Read it "
        "first and implement it, with tests for the behavior it adds or changes. If the code already does what the plan "
        "asks, change nothing and answer `unchanged`. Otherwise change the files the plan needs and answer `implemented`. "
        f"You may add, change and delete plain files anywhere in the repository, at most {rules.max_paths} files of at most "
        f"{rules.file_cap // MiB} MiB each, except: any path with a component starting with `.git`, anything under "
        f"`{'`, `'.join(rules.excluded)}`, executable files and symlinks. The plan's own folder may change too (for example "
        f"an \"As built\" section). {step_text.GIT_WRITES} Do not add or upgrade dependencies. Before answering, run the "
        "project's static analysis and tests where you can and fix what they report; your runs are evidence for you, and "
        "after this step the factory's own checks decide. With `implemented`, list in `paths` every file you changed, "
        "added or deleted and give a one-line commit `message`; the factory commits exactly those paths. Remove any other "
        "file you created. Anything left uncommitted is reported back to you as a failed step. In `explanation`, say which "
        "commands you ran and how they ended, and name every test file you added. If you could not finish, answer "
        "`incomplete`; if the plan cannot be implemented as written or needs a decision, answer `needs_owner`; say why in "
        "`explanation`."
    )


def repeat_instructions(number: int, *, unrecorded: bool) -> str:
    """A repeat's fixed instructions for the implement step. `unrecorded`: attempt `number` answered `implemented` and
    nothing of it was committed, so its files must be listed again."""
    last = (
        f"Nothing of attempt {number} was committed, so none of its files is in Git: answer `implemented` and list in "
        "`paths` again every file you want committed."
        if unrecorded
        else "If you only removed or restored files, answer `unchanged`: an `implemented` answer with nothing new to commit "
        "is rejected for good."
    )
    return (
        "Remove every untracked file listed that you do not want committed. Restore every tracked file you changed or "
        "deleted and do not want committed (`git show HEAD:<path> > <path>`); you cannot run `git checkout` or `git "
        f"restore`. With `implemented`, `paths` lists every file you want committed, changed, added or deleted. {last}"
    )


def feedback(found: Unsettled, rules: StepRules, number: int, task: str, nonce: str, *, unrecorded: bool) -> str:
    """The next attempt's complete input in the shared frame (`step_text.feedback`): the implement step's fixed words for
    the reason, the listing, its fixed instructions, then the task. `found.reason` is one of REPEATABLE."""
    opening = next(text for reason, text in OPENING.items() if reason == found.reason)
    instructions = repeat_instructions(number, unrecorded=unrecorded)
    return step_text.feedback(opening.format(number=number), found.listing, instructions, task, nonce)


def artifact(_tip: Tree, _rules: StepRules) -> None:
    """No artifact rule at X: `Verified.blob` stays NULL."""
    return None
