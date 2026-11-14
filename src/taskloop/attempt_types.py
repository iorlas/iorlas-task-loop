"""Typed attempt facts of any step; none of these records grants admission."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol

from any_agent import RunOutcome, classify
from any_agent.procs import Worker
from git_porcelain import Repo

from taskloop.agents.settings import AgentSetting
from taskloop.answer_failures import AnswerFailureData
from taskloop.repo import RepoId
from taskloop.task import TaskReference


class Checkouts(Protocol):
    """A fresh Git view from one checkout path. On a slot, `git_dir` is the Git directory its pointer check verified:
    every call of that view then uses it and never reads `<slot>/.git` again (a pointer swapped after the check is not
    followed), and a call on any other path is `NotARepo`; without it (the person's checkout) `.git` is read per call."""

    def __call__(self, path: Path, /, *, git_dir: Path | None = None) -> Repo: ...


# The registered worker and its process group observed gone (True), or alive/unknown (False); never descendant proof.
type WorkerGone = Callable[[Worker], bool]
type Seen = Literal["matching", "gone", "different_process", "unknown"]
type EntryIdentity = tuple[int, str, str]  # a registered entry's (pid, start, boot)


class Identified(Protocol):
    @property
    def pid(self) -> int: ...
    @property
    def start(self) -> str: ...
    @property
    def boot(self) -> str: ...


def entry_identity(process: Identified) -> EntryIdentity:
    """The one spelling of an entry's identity from an observed or registered process."""
    return process.pid, process.start, process.boot


type Observe = Callable[[EntryIdentity], Seen]  # a native process-table read of a registered entry; no spawn or signal
TRAILER: Final = "Task-Loop-Attempt"  # the factory's commit trailer; an agent's message may never carry it
MiB: Final = 1 << 20
MODE: Final = "100644"
ATTEMPTS: Final = 3  # attempts of one step at most (2 repeats); always compared as `number >= ATTEMPTS`
MIN_GIT_READ_SECONDS: Final = 30
MAX_GIT_READ_SECONDS: Final = 86400  # a day; a larger value overflows the process timeout
DEFAULT_GIT_READ_SECONDS: Final = 600  # seconds a Git read may take before it is `unavailable:git` (the machine config's default)
type RepeatReason = Literal["uncommitted", "unsafe", "ignored"]
REPEATABLE: Final[tuple[RepeatReason, ...]] = ("uncommitted", "unsafe", "ignored")  # the only leftovers a repeat hands back
# What a valid answer does to the slot: `commit` ends at a new commit X != B, `keep` ends at B itself, `none` ends nothing.
type Effect = Literal["commit", "keep", "none"]
EFFECTS: Final[tuple[Effect, ...]] = ("commit", "keep", "none")
type Step = Literal["plan", "implement"]  # the built steps (`attempt.step`), in order; each has its kind in `steps`


@dataclass(frozen=True)
class StepRules:
    """What one step may commit: files under `root` (ending in `/`, or `""` for the whole repository), at most
    `max_paths` of them, each at most `file_cap` bytes, none under an `excluded` prefix; `deletions`: a listed path may
    be a file the step deleted (each kind brings its own rules)."""

    root: str
    max_paths: int = 32
    file_cap: int = MiB
    deletions: bool = False
    excluded: tuple[str, ...] = ()


class Unreadable(Exception):
    """A read that cannot be told apart from a failure returned nothing: the parent of X, a listed blob, or a listed
    path's entry. The library reads these with an unchecked exit code, so None is never taken as evidence."""


@dataclass(frozen=True)
class FileStat:
    """One `lstat`, never following a symlink: the kind, the size and whether any execute bit is set."""

    kind: Literal["file", "dir", "link", "other"]
    size: int
    executable: bool


class SlotFiles(Protocol):
    """The narrow file port over a slot and its Git pointer: plain reads, no Git, nothing written."""

    def lstat(self, path: Path) -> FileStat | None:
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
    slot_path: str
    input_ref: FileRef
    setting: AgentSetting
    deadline: float
    entry: EntryIdentity
    number: int  # the attempt's number in its step (1, 2, 3), admitted with it
    step: str  # the step the attempt belongs to (`plan`, `implement`), admitted with it
    after_commit: str | None = None  # attempt 1 of a later step: the previous step's published X, which it starts from
    source_checks_id: str | None = None  # a clean-slot repeat after failed checks; never a dirty-slot takeover


@dataclass(frozen=True)
class Replaced:
    """The launcher's observation that the stored entry process no longer runs; the store cannot verify it."""

    identity: EntryIdentity
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
    end_commit: str | None = None  # the commit the step ends at (X, or B when its effect is `keep`), written once
    start: str | None = None  # E: where the previous attempt ended (its X, else its B), read frozen; None for attempt 1


@dataclass(frozen=True)
class ChainLink:
    """One dispatched attempt of a step as the chain verdict reads it (frozen once a successor exists): its B, its X
    (None until stored), its valid answer's effect and committed paths, and its admitted input."""

    number: int
    base_commit: str
    end_commit: str | None
    effect: Effect | None
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
    turns: int | None  # model requests during this attempt
    session: str | None
    usage_incomplete: bool | None = None


@dataclass(frozen=True)
class AnswerState:
    kind: Literal["validation_pending", "valid", "missing", "json_invalid", "schema_invalid"]
    disposition: str | None = None
    effect: Effect | None = None  # stored with the disposition of a valid answer; the store's fences read it
    paths: tuple[str, ...] = ()  # the files the agent asked the factory to commit, as validated
    message: str | None = None
    failure: AnswerFailureData | None = None


# Every verdict rule word: the chain's (CHAIN_RULES, any step) and each step kind's artifact rules (`steps.RULES` has all).
class PlanContentRule(StrEnum):
    CHANGE_MAP = "plan_change_map"
    DEPTH = "plan_depth"
    HEADING = "plan_heading"


type Rule = PlanContentRule | Literal[
    "commit_absent", "not_descendant", "chain_length", "paths", "mode", "file_size", "nothing_written", "plan_missing",
    "plan_encoding", "plan_empty", "plan_size",
]
CHAIN_RULES: Final[tuple[Rule, ...]] = (
    "commit_absent", "not_descendant", "chain_length", "paths", "mode", "file_size", "nothing_written",
)


@dataclass(frozen=True)
class Verified:
    """Every rule held over the step's chain (B1, each attempt's commit, the step's artifact at Xn); `blob`: that
    artifact's blob (the plan's), None for a step kind without one; `reused`: no attempt of the step committed anything,
    what B1 holds stands."""

    blob: str | None
    reused: bool = False


@dataclass(frozen=True)
class Rejected:
    """The first rule the step's commit broke (or `nothing_written`: no commit at all); terminal for the attempt."""

    reason: Rule


@dataclass(frozen=True)
class PathExplanation:
    """A rejected path and the owning check's explanation, without file content."""

    path: str
    explanation: str

    def __post_init__(self) -> None:
        if not self.explanation.strip():
            raise ValueError("A refused path needs an explanation")


@dataclass(frozen=True)
class Unsettled:
    """The slot is not settled (`unborn`, `branch`, `head_moved`, `dirty`, `redirected`, `worker_alive`, `superseded`,
    `staged`, `uncommitted`, `unsafe`, `ignored`); nothing stored, retryable. `listing` is data for a person and a repeat's
    feedback (the leftovers, the unsafe path, the ignored paths), never parsed."""

    reason: str
    listing: tuple[str, ...] = ()
    explanations: tuple[PathExplanation, ...] = field(default=(), compare=False)


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
    session_state: Literal["complete", "pending", "conflict", "fault"]  # the session ref's capture, never a git push
    verification: Verdict | None = None


@dataclass(frozen=True)
class SessionInput:
    first_ref: str | None = None
    conflict: bool = False
    fault: str | None = None


@dataclass(frozen=True)
class PendingResult:
    admission: Admission
    raw: RunOutcome
    facts: ExecutionFacts | None
    sessions: SessionInput
    evidence: Evidence | None = None


@dataclass(frozen=True)
class CaptureResult:
    status: Literal["accepted", "already_same", "conflict", "unavailable"]
    reason: str = ""


@dataclass(frozen=True)
class AttemptResult:
    status: Literal["refused", "pending", "collected", "conflict", "unavailable"]
    reason: str = ""
    execution: StoredExecution | None = None
    pending: PendingResult | None = None
    explanation: str = ""


@dataclass(frozen=True)
class Answer:
    """A step kind decoder's one result: the step's own `disposition` word (for display), its `effect` (what the factory
    does), and `paths` and `message`: what the agent asks the factory to commit (only with effect `commit`); the agent
    never commits."""

    disposition: str
    effect: Effect
    paths: tuple[str, ...]
    message: str | None
    explanation: str


def dot_git(name: str) -> bool:
    """A name that starts with `.git` for Git or for a file system that ignores case and some code points (HFS+ drops
    zero-width and bidi marks): format characters (Unicode category Cf: U+200B-U+200F, U+202A-U+202E, U+2060-U+206F,
    U+FEFF, ...) are removed, then the name is case folded."""
    return "".join(c for c in name if unicodedata.category(c) != "Cf").casefold().startswith(".git")


def path_allowed(path: str, rules: StepRules) -> bool:
    """A path the step may commit: at most 255 bytes, relative, under `rules.root` and under no `rules.excluded` prefix,
    no NUL, newline or backslash, and no empty, `.` or `..` component nor one that starts with `.git` in any case (macOS
    file systems ignore case)."""
    if len(path.encode("utf-8", "surrogatepass")) > 255 or any(c in path for c in "\0\n\\") or not path.startswith(rules.root):
        return False
    if any(path.casefold().startswith(prefix.casefold()) for prefix in rules.excluded):  # case: as `.git` above
        return False
    parts = path.split("/")
    return len(path) > len(rules.root) and not any(p in ("", ".", "..") or dot_git(p) for p in parts)


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
        optional_int(s.res.get("requests")),
        ref if isinstance(ref := s.res.get("ref"), str) and ref else None,
        incomplete if isinstance(incomplete := s.res.get("usage_incomplete"), bool) else None,
    )
