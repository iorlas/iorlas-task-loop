"""Typed answer contract failures and their single durable representation."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AnswerRule(StrEnum):
    MISSING = "missing"
    JSON = "json"
    SHAPE = "shape"
    DISPOSITION = "disposition"
    PLAN_PATH = "plan_path"
    PATHS_SHAPE = "paths_shape"
    PATHS_COUNT = "paths_count"
    PATHS_DUPLICATE = "paths_duplicate"
    PATHS_LOCATION = "paths_location"
    PATHS_REQUIRED = "paths_required"
    PLAN_FORBIDDEN = "plan_forbidden"
    MESSAGE = "message"
    EXPLANATION = "explanation"


class AnswerFailureData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: AnswerRule
    explanation: str = Field(strict=True, min_length=1, max_length=2000)

    def describe(self) -> str:
        return f"{self.rule.value}: {self.explanation}"


class AnswerFailure(ValueError):
    """A decoder rejection remains compatible with callers expecting ValueError."""

    def __init__(self, rule: AnswerRule, explanation: str) -> None:
        self.data = AnswerFailureData(rule=rule, explanation=explanation)
        super().__init__(self.data.describe())

    @property
    def rule(self) -> AnswerRule:
        return self.data.rule

    @property
    def explanation(self) -> str:
        return self.data.explanation


def encode(failure: AnswerFailureData | None) -> str | None:
    return None if failure is None else failure.model_dump_json()


def validate(failure: AnswerFailureData | None, kind: str) -> AnswerFailureData | None:
    """Failure presence and rule must agree with the answer phase, in process and after loading."""
    if kind in ("valid", "validation_pending"):
        if failure is not None:
            raise ValueError("Usable or pending answers cannot have failure data")
        return None
    if failure is None:
        raise ValueError("Invalid or missing answers require failure data")
    expected = {"missing": AnswerRule.MISSING, "json_invalid": AnswerRule.JSON}
    if kind in expected:
        if failure.rule != expected[kind]:
            raise ValueError("Answer phase and failure rule disagree")
    elif kind != "schema_invalid" or failure.rule in (AnswerRule.MISSING, AnswerRule.JSON):
        raise ValueError("Answer phase and failure rule disagree")
    return failure


def decode(value: object, kind: str) -> AnswerFailureData | None:
    """Validate both the durable payload and its association with the stored answer phase."""
    if value is None:
        return validate(None, kind)
    if not isinstance(value, str):
        raise ValueError("Failure data must be stored as JSON text")
    return validate(AnswerFailureData.model_validate_json(value), kind)
