"""Typed admitted-plan facts; none of these records grants admission."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from any_agent import RunOutcome, classify
from any_agent.procs import Worker
from git_porcelain import Repo

from taskloop.repo import RepoId
from taskloop.task import TaskReference

DISPOSITIONS: Final = ("planned", "incomplete", "needs_owner")
type Checkouts = Callable[[Path], Repo]  # a fresh Git view from one checkout path


@dataclass(frozen=True)
class AttemptKey:
    attempt_id: str
    dispatch_token: str
    reservation_generation: int


@dataclass(frozen=True)
class FileRef:
    path: str
    digest: str


@dataclass(frozen=True)
class Admission:
    key: AttemptKey
    task: TaskReference
    repo_id: RepoId
    slot: str
    cwd: str
    input_ref: FileRef
    model: str
    effort: str
    sandbox: str
    deadline: float
    entry: tuple[int, str, str]

    @property
    def plan_path(self) -> str:
        return f"docs/design/{self.task.task_id}/plan.md"


@dataclass(frozen=True)
class Replaced:
    """The launcher's observation that the stored entry process no longer runs; the store cannot verify it."""

    identity: tuple[int, str, str]
    seen: Literal["gone", "different_process"]


@dataclass(frozen=True)
class AttemptRecord:
    admission: Admission
    phase: str
    revision: int
    worker: Worker | None
    session_ref: str | None
    session_conflict: bool
    base_commit: str | None  # B: the slot HEAD read just before dispatch; never part of the fenced Admission


@dataclass(frozen=True)
class Evidence:
    stdout: FileRef
    stderr: FileRef
    answer: FileRef
    diagnostics: FileRef


@dataclass(frozen=True)
class ExecutionFacts:
    rc: int | None
    timed_out: bool
    stop: str | None
    watch: str | None
    work: bool
    stands: bool
    answered: bool | None
    reason: str | None
    http_status: int | None
    tokens: tuple[int | None, int | None, int | None] | None
    cumulative: tuple[int | None, int | None, int | None] | None
    turns: int | None
    session: str | None
    cost_usd: None = None


@dataclass(frozen=True)
class AnswerState:
    kind: Literal["validation_pending", "valid", "missing", "json_invalid", "schema_invalid"]
    disposition: str | None = None
    plan_path: str | None = None
    commit: str | None = None


type Rule = Literal[
    "commit_absent", "not_descendant", "chain_length", "merge", "paths", "mode", "plan_missing", "plan_encoding", "plan_empty", "plan_size"
]
RULES: Final[tuple[Rule, ...]] = (
    "commit_absent", "not_descendant", "chain_length", "merge", "paths", "mode", "plan_missing", "plan_encoding", "plan_empty", "plan_size"
)


@dataclass(frozen=True)
class Verified:
    """Every rule held over (B, X, the chain, the plan blob); `reused`: X is B, so nothing new was committed."""

    plan_blob: str
    reused: bool = False


@dataclass(frozen=True)
class Rejected:
    """The first rule the reported commit broke; terminal for the attempt."""

    reason: Rule


@dataclass(frozen=True)
class Unsettled:
    """The slot is not detached, born and clean at X (`unborn`, `branch`, `head_moved`, `dirty`); nothing stored, retryable."""

    reason: str


@dataclass(frozen=True)
class NotApplicable:
    """No valid `planned` answer of a clean run to verify; `what` is the stored outcome."""

    what: str


@dataclass(frozen=True)
class VerifyRefused:
    reason: str


@dataclass(frozen=True)
class VerifyUnavailable:
    """Unknown: nothing stored (`git:<Type>`, `repo`, `not_listed`, `store`, `validation_pending`, `inconsistent`)."""

    reason: str


type Verdict = Verified | Rejected
type VerifyResult = Verified | Rejected | Unsettled | NotApplicable | VerifyRefused | VerifyUnavailable


@dataclass(frozen=True)
class StoredExecution:
    key: AttemptKey
    facts: ExecutionFacts
    evidence: Evidence
    answer: AnswerState
    publication: Literal["complete", "pending", "conflict", "fault"]
    verification: Verdict | None = None
    custody: Literal["unresolved"] = "unresolved"


@dataclass(frozen=True)
class SessionInput:
    first_ref: str | None = None
    conflict: bool = False
    fault: str | None = None


@dataclass(frozen=True)
class PendingPlanResult:
    admission: Admission
    raw: RunOutcome
    facts: ExecutionFacts | None
    sessions: SessionInput
    evidence: Evidence | None = None


@dataclass(frozen=True)
class PublicationResult:
    status: Literal["accepted", "already_same", "conflict", "unavailable"]
    reason: str = ""


@dataclass(frozen=True)
class AttemptResult:
    status: Literal["refused", "pending", "collected", "conflict", "unavailable"]
    reason: str = ""
    execution: StoredExecution | None = None
    pending: PendingPlanResult | None = None


@dataclass(frozen=True)
class PlanAnswer:
    disposition: str
    plan_path: str | None
    commit: str | None
    explanation: str


type PlanDecoder = Callable[[object, str], PlanAnswer]


def decode_plan_answer(value: object, expected_path: str) -> PlanAnswer:
    """Validate the factory's reported plan contract, without verifying Git effects; the single owner of its cross-field rule."""
    if isinstance(value, dict) and set(value) == {"disposition", "plan_path", "commit", "explanation"}:
        disposition, path, commit, explanation = (value[key] for key in ("disposition", "plan_path", "commit", "explanation"))
        valid_commit = commit is None or (
            isinstance(commit, str) and len(commit) in (40, 64) and all(c in "0123456789abcdef" for c in commit)
        )
        if (
            disposition in DISPOSITIONS
            and (path is None or path == expected_path)
            and valid_commit
            and isinstance(explanation, str)
            and len(explanation) <= 2000
            and (disposition != "planned" or (path == expected_path and isinstance(commit, str)))
        ):
            return PlanAnswer(disposition, path, commit, explanation)
    raise ValueError("Invalid plan answer")


def optional_int(value: object) -> int | None:
    """A reported nonnegative count, else unknown (never an invented zero)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(value: object) -> tuple[int | None, int | None, int | None] | None:
    if isinstance(value, dict):
        counts = (optional_int(value.get("in")), optional_int(value.get("cached")), optional_int(value.get("out")))
        return None if counts == (None, None, None) else counts
    return None


def execution_facts(raw: RunOutcome) -> ExecutionFacts:
    """Project normalized library facts only; raw diagnostics remain file evidence."""
    s = raw.summary
    measured = s.facts.copy()
    if raw.watch.why:
        measured["watchdog"] = raw.watch.why
    if raw.secret:
        measured["secret"] = raw.secret
    if raw.net:
        measured["net_up"] = False
    outcome = classify(raw.rc, s.vendor, s.stderr, raw.timed_out, s.work, measured)
    answered = s.res.get("answered")
    return ExecutionFacts(
        raw.rc,
        raw.timed_out,
        raw.stop,
        raw.watch.why,
        s.work,
        s.stands,
        answered if isinstance(answered, bool) else None,
        outcome.reason if outcome else None,
        optional_int(s.facts.get("http_status")),
        _usage(s.res.get("tokens")),
        _usage(s.res.get("cumulative")),
        optional_int(s.res.get("turns")),
        ref if isinstance(ref := s.res.get("ref"), str) and ref else None,
    )
