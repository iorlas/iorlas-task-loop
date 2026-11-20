"""A workflow: the Git-versioned file that gives each agent step its agent choice and ordered prompt sections
(`.task-loop/workflows/<name>.toml`, decisions 1-4, 14 and 15 of docs/design/tl-8bh9.14.117/plan.md).

`load` turns the file's bytes into a frozen `Workflow` or a typed `WorkflowRefused`; it reads nothing else. A section is
verbatim `text` or `use = <renderer>` (a closed set the code renders); there are no placeholders. The contract and safety
sentences, the plan template and the answer schema stay in code and are appended after the sections, never listed here."""

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from taskloop.frame_markers import RESERVED
from taskloop.harness_choice import HarnessKind
from taskloop.step import ATTEMPTS, Step

MAX_BYTES: Final = 64 * 1024


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class Renderer(StrEnum):
    """What a `use` section may name: the two factory blocks that need values the code holds."""

    TASK = "task"
    INPUT_CONTEXT = "input_context"


class Reason(StrEnum):
    """Why a file is refused (decision 15)."""

    MISSING = "missing"
    NOT_A_FILE = "not_a_file"
    TOO_LARGE = "too_large"
    NOT_TOML = "not_toml"
    UNKNOWN_KEY = "unknown_key"
    UNKNOWN_KIND = "unknown_kind"
    UNKNOWN_RENDERER = "unknown_renderer"
    RESERVED_MARKER = "reserved_marker"
    BAD_VALUE = "bad_value"


class Section(Input):
    """One entry of a step's prompt: exactly one of verbatim `text` or a `use` renderer."""

    text: str | None = None
    use: Renderer | None = None

    @model_validator(mode="after")
    def one_of_text_or_use(self) -> Self:
        if (self.text is None) == (self.use is None):
            raise ValueError("a section has exactly one of `text` or `use`")
        if self.text is not None and not self.text.strip():
            raise ValueError("a text section is not empty")
        if self.text is not None and any(name in self.text for name in RESERVED):
            raise ReservedMarker(self.text)
        return self


class ReservedMarker(ValueError):
    """A text section holds the name of a factory data block."""


class Agent(Input):
    """The agent choice of a step; an absent key falls to machine configuration. Sandbox and credentials are never here."""

    harness: HarnessKind | None = None
    model: str | None = None
    effort: str | None = None
    compaction_token_limit: int | None = Field(default=None, strict=True, gt=0)

    @field_validator("model", "effort")
    @classmethod
    def word(cls, value: str | None) -> str | None:
        """One printable word, so an empty or odd value is refused at load and never silently ignored."""
        if value is not None and (not value or value.startswith("-") or not value.isprintable() or any(c.isspace() for c in value)):
            raise ValueError("must be one printable word that does not start with '-'")
        return value


class StepTable(Input):
    """One step kind's table: its agent and its ordered prompt, which names `input_context` exactly once."""

    agent: Agent = Agent()
    prompt: tuple[Section, ...]

    @model_validator(mode="after")
    def input_context_once(self) -> Self:
        if sum(each.use is Renderer.INPUT_CONTEXT for each in self.prompt) != 1:
            raise ValueError("the prompt names the input_context renderer exactly once")
        return self


class ImplementTable(StepTable):
    """The implement table, the only one with a cap on its check-driven repeats (below the engine's ATTEMPTS ceiling)."""

    max_attempts: int | None = Field(default=None, strict=True, ge=1)

    @field_validator("max_attempts")
    @classmethod
    def below_the_ceiling(cls, value: int | None) -> int | None:
        if value is not None and value > ATTEMPTS:
            raise ValueError("max_attempts is at most the engine's ceiling")
        return value


class Steps(Input):
    """Keyed by kind, so a duplicate, missing or misordered kind cannot be written; the check step has no table."""

    plan: StepTable
    implement: ImplementTable
    feedback: tuple[Section, ...] = Field(min_length=1)  # the opening of a failed-check input: verbatim text sections only

    @field_validator("feedback")
    @classmethod
    def text_only(cls, value: tuple[Section, ...]) -> tuple[Section, ...]:
        if any(each.text is None for each in value):
            raise ValueError("a feedback section is verbatim text")
        return value


class Workflow(Input):
    step: Steps

    @property
    def implement_cap(self) -> int:
        """Attempts of the implement step at most when a failed check repeats it; the file's `max_attempts`, else the ceiling."""
        return self.step.implement.max_attempts or ATTEMPTS

    def table(self, step: Step) -> StepTable:
        match step:
            case Step.PLAN:
                return self.step.plan
            case Step.IMPLEMENT:
                return self.step.implement


@dataclass(frozen=True)
class WorkflowRefused:
    reason: Reason
    where: str  # the path of the offending key in the file, dotted; empty for a whole-file refusal


def load(data: bytes) -> Workflow | WorkflowRefused:
    """The file's bytes as a workflow, or the first refusal; nothing is read but `data`."""
    if len(data) > MAX_BYTES:
        return WorkflowRefused(Reason.TOO_LARGE, "")
    try:
        table = tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError, tomllib.TOMLDecodeError:
        return WorkflowRefused(Reason.NOT_TOML, "")
    try:
        return Workflow.model_validate(table)
    except ValidationError as error:
        return _refusal(error)


def _refusal(error: ValidationError) -> WorkflowRefused:
    """Map pydantic's first structured error (its `type` and `loc`, never its text) to a closed reason."""
    first = error.errors()[0]
    location = first["loc"]
    where = ".".join(str(part) for part in location)
    kind = first["type"]
    if kind == "extra_forbidden":
        unknown_kind = len(location) == 2 and location[0] == "step"
        return WorkflowRefused(Reason.UNKNOWN_KIND if unknown_kind else Reason.UNKNOWN_KEY, where)
    if kind == "enum" and location[-1] == "use":
        return WorkflowRefused(Reason.UNKNOWN_RENDERER, where)
    if kind == "value_error" and isinstance(first.get("ctx", {}).get("error"), ReservedMarker):
        return WorkflowRefused(Reason.RESERVED_MARKER, where)
    return WorkflowRefused(Reason.BAD_VALUE, where)
