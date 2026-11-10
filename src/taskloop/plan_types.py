"""Typed admitted-plan facts; none of these records grants admission."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from any_agent import RunOutcome, classify
from any_agent.procs import Worker
from git_porcelain import Repo

from taskloop.repo import RepoId
from taskloop.task import TaskReference

DISPOSITIONS: Final = ("planned", "unchanged", "incomplete", "needs_owner")
type Checkouts = Callable[[Path], Repo]  # a fresh Git view from one checkout path
# The registered worker and its process group observed gone (True), or alive/unknown (False); never descendant proof.
type WorkerGone = Callable[[Worker], bool]
TRAILER: Final = "Task-Loop-Attempt"  # the factory's commit trailer; an agent's message may never carry it
PLAN_NAME: Final = "plan.md"
MiB: Final = 1 << 20
ATTEMPTS: Final = 3  # attempts of one step at most (2 repeats); always compared as `number >= ATTEMPTS`
type RepeatReason = Literal["uncommitted", "unsafe", "ignored"]
REPEATABLE: Final[tuple[RepeatReason, ...]] = ("uncommitted", "unsafe", "ignored")  # the only leftovers a repeat hands back


@dataclass(frozen=True)
class StageRules:
    """What one stage may commit: files under `root` (ending in `/`), at most `max_paths` of them, each at most `file_cap`
    bytes; `deletions` is False for the plan stage (the implementation and review stages bring their own rules)."""

    root: str
    max_paths: int = 32
    file_cap: int = MiB
    deletions: bool = False


def plan_stage(task_id: str) -> StageRules:
    """The plan stage's rules: its files live under `docs/design/<task-id>/`, the plan itself is `plan.md` there."""
    return StageRules(f"docs/design/{task_id}/")


@dataclass(frozen=True)
class FileEntry:
    """One `lstat`, never following a symlink: the kind, the size and whether any execute bit is set."""

    kind: Literal["file", "dir", "link", "other"]
    size: int
    executable: bool


class SlotFiles(Protocol):
    """The narrow file port over a slot and its Git pointer: plain reads, no Git, nothing written."""

    def lstat(self, path: Path) -> FileEntry | None:
        """None when nothing is there or it cannot be read."""
        ...

    def read(self, path: Path, cap: int) -> bytes | None:
        """The bytes of a regular file (checked by `lstat` before any open) of at most `cap` bytes; else None."""
        ...

    def resolve(self, path: Path) -> Path | None:
        """The path with every symlink and `..` resolved as the operating system (and so Git) resolves it; None when it
        does not exist or cannot be resolved."""
        ...


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
    number: int  # the attempt's number in its step (1, 2, 3), admitted with it

    @property
    def rules(self) -> StageRules:
        return plan_stage(self.task.task_id)


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
    plan_commit: str | None = None  # the commit the stage ends at (X, or B for `unchanged`), written once
    start: str | None = None  # E: where the previous attempt ended (its X, else its B), read frozen; None for attempt 1


@dataclass(frozen=True)
class StepAttempt:
    """One dispatched attempt of a step as the chain verdict reads it (frozen once a successor exists): its B, its X
    (None until stored), its valid answer's disposition and committed paths, and its admitted input."""

    number: int
    base_commit: str
    plan_commit: str | None
    disposition: str | None
    paths: tuple[str, ...]
    input_ref: FileRef


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
    paths: tuple[str, ...] = ()  # the files the agent asked the factory to commit, as validated
    message: str | None = None


type Rule = Literal[
    "commit_absent", "not_descendant", "chain_length", "paths", "mode", "file_size", "nothing_written", "plan_missing",
    "plan_encoding", "plan_empty", "plan_size",
]
RULES: Final[tuple[Rule, ...]] = (
    "commit_absent", "not_descendant", "chain_length", "paths", "mode", "file_size", "nothing_written", "plan_missing",
    "plan_encoding", "plan_empty", "plan_size",
)


@dataclass(frozen=True)
class Verified:
    """Every rule held over the step's chain (B1, each attempt's commit, the plan blob at Xn); `reused`: no attempt of
    the step committed anything, the plan at B1 stands."""

    plan_blob: str
    reused: bool = False


@dataclass(frozen=True)
class Rejected:
    """The first rule the stage's commit broke (or `nothing_written`: no commit at all); terminal for the attempt."""

    reason: Rule


@dataclass(frozen=True)
class Unsettled:
    """The slot is not settled (`unborn`, `branch`, `head_moved`, `dirty`, `redirected`, `worker_alive`, `superseded`,
    `staged`, `uncommitted`, `unsafe`, `ignored`); nothing stored, retryable. `listing` is data for a person and a repeat's
    feedback (the leftovers, the unsafe path, the ignored paths), never parsed."""

    reason: str
    listing: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotApplicable:
    """No valid `planned` or `unchanged` answer of a clean run to verify; `what` is the stored outcome."""

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
    """`paths` and `message`: what the agent asks the factory to commit (only with `planned`); the agent never commits."""

    disposition: str
    plan_path: str | None
    paths: tuple[str, ...]
    message: str | None
    explanation: str


type PlanDecoder = Callable[[object, StageRules], PlanAnswer]
ANSWER_KEYS: Final = ("disposition", "plan_path", "paths", "message", "explanation")


def dot_git(name: str) -> bool:
    """A name that starts with `.git` for Git or for a file system that ignores case and some code points (HFS+ drops
    zero-width and bidi marks): format characters (Unicode category Cf: U+200B-U+200F, U+202A-U+202E, U+2060-U+206F,
    U+FEFF, ...) are removed, then the name is case folded."""
    return "".join(c for c in name if unicodedata.category(c) != "Cf").casefold().startswith(".git")


def path_allowed(path: str, rules: StageRules) -> bool:
    """A path the stage may commit: at most 255 bytes, relative, under `rules.root`, no NUL, newline or backslash, and no
    empty, `.` or `..` component nor one that starts with `.git` in any case (macOS file systems ignore case)."""
    if len(path.encode("utf-8", "surrogatepass")) > 255 or any(c in path for c in "\0\n\\") or not path.startswith(rules.root):
        return False
    parts = path.split("/")
    return len(path) > len(rules.root) and not any(p in ("", ".", "..") or dot_git(p) for p in parts)


def _message(message: object) -> bool:
    return (
        isinstance(message, str) and 1 <= len(message) <= 500 and "\0" not in message and TRAILER.casefold() + ":" not in message.casefold()
    )


def _paths(paths: object, rules: StageRules) -> tuple[str, ...] | None:
    if not isinstance(paths, list) or len(paths) > rules.max_paths:
        return None
    found = tuple(path for path in paths if isinstance(path, str) and path_allowed(path, rules))
    return found if len(found) == len(paths) and len(set(found)) == len(found) else None


def decode_plan_answer(value: object, rules: StageRules) -> PlanAnswer:
    """Validate the factory's plan answer contract, without verifying Git effects; the single owner of its cross-field
    rules and every bound (the strict schema carries none). The expected plan is `<rules.root>plan.md`."""
    if not isinstance(value, dict) or set(value) != set(ANSWER_KEYS):
        raise ValueError("Invalid plan answer")
    disposition, path, paths, message, explanation = (value[key] for key in ANSWER_KEYS)
    expected, listed = rules.root + PLAN_NAME, _paths(paths, rules)
    if disposition == "planned":
        fits = path == expected and listed is not None and expected in listed and _message(message)
    else:
        named = path == expected or (path is None and disposition != "unchanged")
        fits = disposition in DISPOSITIONS and named and listed == () and message is None
    if not fits or listed is None or not isinstance(explanation, str) or len(explanation) > 2000:
        raise ValueError("Invalid plan answer")
    text = message if isinstance(message, str) else None
    return PlanAnswer(str(disposition), None if path is None else expected, listed, text, explanation)


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
