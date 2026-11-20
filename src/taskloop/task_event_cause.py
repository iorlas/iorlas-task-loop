"""Validated hold causes and the context captured by the deciding operation; no execution or storage imports."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taskloop.agents.api import AgentStop
from taskloop.answer_failures import AnswerFailureData, AnswerRule
from taskloop.command_conclusion import CommandConclusion


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


type Text = Annotated[str, Field(min_length=1)]


class Family(StrEnum):
    DISPOSITION = "disposition"
    RUN = "run"
    ANSWER = "answer"
    REJECTION = "rejection"
    CHECKS = "checks"
    STUCK = "stuck"
    REPEAT = "repeat"
    MERGE = "merge"
    LAND = "land"
    ROUND = "round"


class DispositionReason(StrEnum):
    INCOMPLETE = "incomplete"
    NEEDS_OWNER = "needs_owner"


class RunReason(StrEnum):
    TIMEOUT = "timeout"
    VENDOR_BLIP = "vendor_blip"
    BAD_REQUEST = "bad_request"
    HUNG = "hung"
    CRASH = "crash"
    KILLED = "killed"
    SECRETS = "secrets"
    EXIT = "exit"
    WORKER_FAILED = "worker_failed"
    LOGGED_OUT = "logged_out"
    RATE_LIMITED = "rate_limited"
    CREDIT_EXHAUSTED = "credit_exhausted"
    NETWORK = "network"
    SETUP = "setup"


class AnswerReason(StrEnum):
    MISSING = "missing"
    JSON_INVALID = "json_invalid"
    SCHEMA_INVALID = "schema_invalid"


class RejectionReason(StrEnum):
    COMMIT_ABSENT = "commit_absent"
    NOT_DESCENDANT = "not_descendant"
    CHAIN_LENGTH = "chain_length"
    PATHS = "paths"
    MODE = "mode"
    FILE_SIZE = "file_size"
    NOTHING_WRITTEN = "nothing_written"
    PLAN_MISSING = "plan_missing"
    PLAN_ENCODING = "plan_encoding"
    PLAN_EMPTY = "plan_empty"
    PLAN_SIZE = "plan_size"
    PLAN_CHANGE_MAP = "plan_change_map"
    PLAN_DEPTH = "plan_depth"
    PLAN_HEADING = "plan_heading"


class ChecksReason(StrEnum):
    MAIN_MOVED = "main_moved"
    EXPIRED = "expired"
    CLAIM_LOST = "claim_lost"
    COMMIT_MISSING = "commit_missing"
    SLOT_UNBORN = "slot:unborn"
    SLOT_MOVED = "slot:moved"
    SLOT_REDIRECTED = "slot:redirected"
    SLOT_BRANCH = "slot:branch"
    ENVIRONMENT_PLATFORM = "environment:platform"
    ENVIRONMENT_PATH_LONG = "environment:path_long"
    ENVIRONMENT_ROOTS = "environment:roots"
    ENVIRONMENT_REMOVE_UNSAFE = "environment:remove_unsafe"
    ENVIRONMENT_PROFILE = "environment:profile"
    ENVIRONMENT_MOVED = "environment:moved"
    ENVIRONMENT_RESET = "environment:reset"
    ENVIRONMENT_DIRTY = "environment:dirty"
    ENVIRONMENT_SANDBOX = "environment:sandbox"


class ProfileReason(StrEnum):
    MISSING = "missing"
    NO_COMMIT = "no_commit"
    NOT_JSON = "not_json"
    NOT_OBJECT = "not_object"
    UNKNOWN_KEY = "unknown_key"
    BAD_VALUE = "bad_value"
    TOO_LARGE = "too_large"
    DUPLICATE_CHECK = "duplicate_check"
    REQUIRED_UNDEFINED = "required_undefined"
    NOT_A_FILE = "not_a_file"


class StuckReason(StrEnum):
    EXPIRED_ADMITTED = "expired_admitted"
    ENTRY_LOST = "entry_lost"
    UNCOLLECTED = "uncollected"
    CONFLICT = "conflict"
    SETUP_FAILED = "setup_failed"
    CHECKS_REFUSED = "checks_refused"


class RepeatReason(StrEnum):
    UNCOMMITTED = "uncommitted"
    UNSAFE = "unsafe"
    IGNORED = "ignored"


class MergeReason(StrEnum):
    BRANCH_DIVERGED = "branch_diverged"
    BRANCH_MOVED = "branch_moved"
    SLOT_MOVED = "slot_moved"
    UNSUPPORTED_CONFLICT = "unsupported_conflict"
    NEEDS_OWNER = "needs_owner"
    EXHAUSTED = "exhausted"
    INVALID_RESOLUTION = "invalid_resolution"
    EXPIRED = "expired"


class LandReason(StrEnum):
    CONFLICT = "conflict"
    CHECKS_FAILED = "checks_failed"
    REMOTE_REJECTED = "remote_rejected"
    BRANCH_MOVED = "branch_moved"
    CLAIM_LOST = "claim_lost"


class RoundReason(StrEnum):
    CLAIM_LOST = "claim_lost"
    BRANCH_MOVED = "branch_moved"


class NotRun(StrEnum):
    NOT_RUN = "not_run"


class FailedCheck(Value):
    name: Text
    conclusion: CommandConclusion | NotRun
    log: Text | None = None

    @model_validator(mode="after")
    def failed(self) -> FailedCheck:
        if self.conclusion is CommandConclusion.PASSED:
            raise ValueError("A failed check cannot have passed")
        return self


class Context(Value):
    explanation: Text | None = None


class DispositionCause(Context):
    family: Literal[Family.DISPOSITION] = Family.DISPOSITION
    reason: DispositionReason
    explanation: Text


class RunCause(Context):
    family: Literal[Family.RUN] = Family.RUN
    reason: RunReason
    deadline: float | None = None
    timed_out: bool | None = None
    rc: int | None = None
    stop: AgentStop | None = None

    @model_validator(mode="after")
    def consistent(self) -> RunCause:
        if self.reason is RunReason.TIMEOUT and self.timed_out is False:
            raise ValueError("A timeout cause cannot deny its timeout")
        timed_out = self.timed_out is True or (self.timed_out is None and self.reason is RunReason.TIMEOUT)
        if self.rc == 0 and not timed_out:
            raise ValueError("A failed run requires a timeout or a failing return code when reported")
        return self


class AnswerCause(Context):
    family: Literal[Family.ANSWER] = Family.ANSWER
    reason: AnswerReason
    failure: AnswerFailureData | None = None

    @model_validator(mode="after")
    def consistent(self) -> AnswerCause:
        if self.failure is not None:
            expected = {AnswerReason.MISSING: AnswerRule.MISSING, AnswerReason.JSON_INVALID: AnswerRule.JSON}
            rule = expected.get(self.reason)
            if (rule is not None and self.failure.rule is not rule) or (
                rule is None and self.failure.rule in (AnswerRule.MISSING, AnswerRule.JSON)
            ):
                raise ValueError("Answer failure rule contradicts the answer kind")
        return self


class RejectionCause(Context):
    family: Literal[Family.REJECTION] = Family.REJECTION
    reason: RejectionReason


class ChecksCause(Context):
    family: Literal[Family.CHECKS] = Family.CHECKS
    reason: ChecksReason | None = None
    check: FailedCheck | None = None
    setup: CommandConclusion | None = None
    profile: ProfileReason | None = None
    checks: tuple[FailedCheck, ...] = ()
    deadline: float | None = None

    @model_validator(mode="after")
    def consistent(self) -> ChecksCause:
        if sum(value is not None for value in (self.reason, self.check, self.setup, self.profile)) != 1:
            raise ValueError("Checks require exactly one deciding failure")
        if self.setup in (CommandConclusion.PASSED, CommandConclusion.UNDEFINED):
            raise ValueError("Setup must have a defined failure conclusion")
        names = tuple(each.name for each in self.checks)
        if len(set(names)) != len(names):
            raise ValueError("Failed check names must be unique")
        if self.check is not None:
            found = next((each for each in self.checks if each.name == self.check.name), None)
            if found is not None and found.conclusion != self.check.conclusion:
                raise ValueError("The deciding check contradicts its context")
        return self


class StuckCause(Context):
    family: Literal[Family.STUCK] = Family.STUCK
    reason: StuckReason
    deadline: float | None = None
    rc: int | None = None
    stop: AgentStop | None = None

    @model_validator(mode="after")
    def consistent(self) -> StuckCause:
        if (self.stop is not None or self.rc is not None) and self.reason is not StuckReason.ENTRY_LOST:
            raise ValueError("Stop context belongs only to a lost entry or a failed run")
        return self


class Leftovers(Value):
    reason: RepeatReason
    paths: tuple[Text, ...]


class RepeatCause(Context):
    family: Literal[Family.REPEAT] = Family.REPEAT
    leftovers: Leftovers | None = None


class MergeCause(Context):
    family: Literal[Family.MERGE] = Family.MERGE
    reason: MergeReason
    explanation: Text
    source: Text | None = None
    target: Text | None = None
    conflicts: tuple[Text, ...] = ()


class LandCause(Context):
    family: Literal[Family.LAND] = Family.LAND
    reason: LandReason
    explanation: Text
    source: Text | None = None
    target: Text | None = None
    checks: tuple[FailedCheck, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> LandCause:
        if self.checks and self.reason is not LandReason.CHECKS_FAILED:
            raise ValueError("Failed checks belong to a checks_failed land refusal")
        return self


class RoundCause(Context):
    family: Literal[Family.ROUND] = Family.ROUND
    reason: RoundReason


type TaskEventCause = Annotated[
    DispositionCause
    | RunCause
    | AnswerCause
    | RejectionCause
    | ChecksCause
    | StuckCause
    | RepeatCause
    | MergeCause
    | LandCause
    | RoundCause,
    Field(discriminator="family"),
]
