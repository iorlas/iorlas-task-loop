"""The step kinds: the few values and functions that make a step the plan step or the implement step. Everything else is
the shared step machinery, which reaches a kind only through `kind(admission.step)`. The set and order of kinds is this
fixed tuple in code, never configuration; only this module imports a kind's own module (`plan_step`, `implement_step`,
an import-linter contract). `next_step` is the one sequencing rule: a task goes plan, then implement, then is done."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from git_porcelain import Tree

from taskloop import implement_step, plan_step
from taskloop.attempt_types import CHAIN_RULES, Answer, Rejected, Rule, Step, StepRules, Unsettled
from taskloop.task import TaskInspection


class Feedback(Protocol):
    def __call__(self, found: Unsettled, rules: StepRules, number: int, task: str, nonce: str, *, unrecorded: bool) -> str:
        """A repeat's complete input: the leftovers `found` as data, the kind's fixed instructions, then `task` (attempt
        1's input). `unrecorded`: attempt `number` asked for a commit and nothing of it was committed."""
        ...


@dataclass(frozen=True)
class StepKind:
    """`rules`: task id to the step's root, caps and deletions. `input_text`: the admitted input. `answer_schema`: the
    strict JSON schema the harness forwards (`schema.json`). `decode`: every bound and cross-field rule of the answer,
    ValueError otherwise. `artifact`: the kind's own rule at X, a broken rule or the artifact's blob (None: the kind has
    no artifact). `feedback`: a repeat's input."""

    step: Step
    rules: Callable[[str], StepRules]
    input_text: Callable[[TaskInspection, StepRules], str]
    answer_schema: Mapping[str, object]
    decode: Callable[[object, StepRules], Answer]
    artifact: Callable[[Tree, StepRules], Rejected | str | None]
    feedback: Feedback


PLAN: Final = StepKind(
    "plan", plan_step.step_rules, plan_step.input_text, plan_step.ANSWER_SCHEMA, plan_step.decode, plan_step.artifact,
    plan_step.feedback,
)
IMPLEMENT: Final = StepKind(
    "implement", implement_step.step_rules, implement_step.input_text, implement_step.ANSWER_SCHEMA, implement_step.decode,
    implement_step.artifact, implement_step.feedback,
)
STEPS: Final[tuple[StepKind, ...]] = (PLAN, IMPLEMENT)  # the fixed step order
# every verdict word a stored verdict may hold
RULES: Final[tuple[Rule, ...]] = CHAIN_RULES + plan_step.ARTIFACT_RULES + implement_step.ARTIFACT_RULES


def kind(step: str) -> StepKind:
    """The kind of a stored or admitted step; an unknown step is a programming error (the schema's CHECK lists the built
    ones)."""
    match step:
        case "plan":
            return PLAN
        case "implement":
            return IMPLEMENT
        case _:
            raise ValueError(f"Unknown step: {step}")


def following(step: str) -> Step | None:
    """The step after `step` in the fixed order; None after the last built step."""
    order = [each.step for each in STEPS]
    at = order.index(kind(step).step)
    return order[at + 1] if at + 1 < len(order) else None


def next_step(current: str | None, done: bool) -> Step | None:
    """What a task admits next. `current`: its current attempt's step, None when it has none or its abandon returned the
    claim (a fresh start: the first step). `done`: that attempt is verified, its release settled (claim kept) and its
    commit published. None: the current attempt's own `Next` applies, or the last step is done."""
    if current is None:
        return STEPS[0].step
    return following(current) if done else None
