"""The step kinds: the few values and functions that make a step the plan step or the implement step. Everything else is
the shared step machinery, which reaches a kind only through `kind(admission.step)`. The set and order of kinds is this
fixed tuple in code, never configuration; only this module imports a kind's own module (`plan_step`, `implement_step`,
an import-linter contract). `next_step` is the one sequencing rule over `ORDER`: a task goes plan, then implement, then
check, then is done. The check step is not a kind (no agent: its attempt is a `checks_attempt`, tl-8bh9.14.6 section 3);
`is_agent` tells the two apart."""

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
    no artifact). `feedback`: a repeat's input. `environment`: the entry prepares the slot's environment (the profile's
    `setup`, `environment.Preparation`) before the agent of attempt 1 starts; a repeat reuses it."""

    step: Step
    rules: Callable[[str], StepRules]
    input_text: Callable[[TaskInspection, StepRules], str]
    answer_schema: Mapping[str, object]
    decode: Callable[[object, StepRules], Answer]
    artifact: Callable[[Tree, StepRules], Rejected | str | None]
    feedback: Feedback
    environment: bool = False


PLAN: Final = StepKind(
    "plan", plan_step.step_rules, plan_step.input_text, plan_step.ANSWER_SCHEMA, plan_step.decode, plan_step.artifact,
    plan_step.feedback,
)
IMPLEMENT: Final = StepKind(
    "implement", implement_step.step_rules, implement_step.input_text, implement_step.ANSWER_SCHEMA, implement_step.decode,
    implement_step.artifact, implement_step.feedback, environment=True,
)
STEPS: Final[tuple[StepKind, ...]] = (PLAN, IMPLEMENT)  # the agent steps, in order
CHECK: Final = "check"  # the checks step: no kind, its own tables (`check_store`)
ORDER: Final = (PLAN.step, IMPLEMENT.step, CHECK)  # every built step, in the fixed order
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


def is_agent(step: str) -> bool:
    """`step` has a kind (an agent attempt, `attempt` row); `check` has none."""
    return any(each.step == step for each in STEPS)


def following(step: str) -> str | None:
    """The step after `step` in `ORDER`; None after the last built step. An unknown step is a programming error."""
    if step not in ORDER:
        raise ValueError(f"Unknown step: {step}")
    at = ORDER.index(step)
    return ORDER[at + 1] if at + 1 < len(ORDER) else None


def next_step(current: str | None, done: bool) -> str | None:
    """What a task admits next. `current`: its current attempt's step, None when it has none or its abandon returned the
    claim (a fresh start: the first step). `done`: that attempt is verified, its release settled (claim kept) and its
    commit published. None: the current attempt's own `Next` applies, or the last step is done."""
    if current is None:
        return STEPS[0].step
    return following(current) if done else None
