"""EngineLog: the union of records an engine run appends to engine/<run>.jsonl (v2). Start/end pairs share an `id`, unique
within the file; an end without its start, or the reverse, is a run that died in between."""
from dataclasses import field
from typing import ClassVar

from taskloop.contracts.checks import CheckRun
from taskloop.contracts.codec import from_tagged, record, table_of
from taskloop.contracts.enums import Outcome, WaitWhat, WhyCode
from taskloop.contracts.trace import Tokens


@record
class LogRec:
    V: ClassVar[int] = 2
    t: float = 0.0  # unset (0): RunLog.emit stamps the time of the append


@record
class RunStart(LogRec):
    KIND: ClassVar[str] = "run_start"
    run: str
    bead: str
    worktree: str
    slot: str | None = None
    prev_run: str = ""
    started_because: str = ""
    ask: str = ""


@record
class StepStart(LogRec):
    KIND: ClassVar[str] = "step_start"
    id: str
    step: str
    text: str = ""
    stage: int | None = None
    stages: int | None = None
    round: int | None = None
    write: int | None = None
    fix: int | None = None


@record
class StepEnd(LogRec):
    KIND: ClassVar[str] = "step_end"
    id: str
    step: str
    outcome: str
    detail: str = ""
    secs: float = 0.0


@record
class CallStart(LogRec):
    KIND: ClassVar[str] = "call_start"
    id: str
    n: int
    step: str
    node: str
    role: str
    resume: bool = False


@record
class CallEnd(LogRec):
    KIND: ClassVar[str] = "call_end"
    id: str
    status: str
    reason: str | None = None
    ref: str = ""
    lane: str = ""
    model: str = ""
    effort: str = ""
    secs: float = 0.0
    tokens: Tokens = field(default_factory=Tokens)
    cost: float = 0.0
    family: str = ""
    flag: str | None = None
    transcript: str = ""
    exit: int | None = None  # the worker's exit code (delegate's answer `exit_code`; negative: ended by that signal)


@record
class CmdStart(LogRec):
    KIND: ClassVar[str] = "cmd_start"
    id: str
    text: str
    cwd: str = ""


@record
class CmdEnd(LogRec):
    KIND: ClassVar[str] = "cmd_end"
    id: str
    exit: int
    secs: float = 0.0
    out: str = ""


@record
class CheckStart(LogRec):
    KIND: ClassVar[str] = "check_start"
    id: str
    check: str
    group: str
    cmd: str
    round: int
    log: str = ""
    timeout_s: float | None = None


@record
class CheckEnd(LogRec):
    KIND: ClassVar[str] = "check_end"
    id: str
    exit: int | None
    status: str
    tries: int = 1
    secs: float = 0.0
    wall_hit: bool = False  # the engine stopped it at its wall limit (start: the CheckStart of the same id; end: this record's t)


@record
class GateStart(LogRec):
    KIND: ClassVar[str] = "gate_start"
    cmd: str
    log: str = ""
    tree: str = ""


@record
class GateEnd(LogRec):
    KIND: ClassVar[str] = "gate_end"
    exit: int | None
    secs: float = 0.0
    skipped: bool = False


@record
class LandTry(LogRec):
    """One try of the land: what main was before the fetch and after it, whether the rebase moved the branch, and the recipe that failed."""

    KIND: ClassVar[str] = "land_try"
    n: int
    base_before: str = ""
    base_after: str = ""
    rebase_moved: bool = False
    failing: str = ""  # "gate", "conflict" or "verify" when the try ended in a fix round; "" when it went on to the push


@record
class WaitStart(LogRec):
    KIND: ClassVar[str] = "wait_start"
    id: str
    what: WaitWhat
    holder: str = ""
    until: float | None = None


@record
class WaitEnd(LogRec):
    KIND: ClassVar[str] = "wait_end"
    id: str
    secs: float
    in_budget: bool = False


@record
class Checks(LogRec):
    """One round of checks: the CheckRun (every check with its result, and what the round's cache saved)."""
    KIND: ClassVar[str] = "checks"
    node_id: str
    run: CheckRun


@record
class Lock(LogRec):
    KIND: ClassVar[str] = "lock"
    what: str
    holder: str = ""


@record
class Unlock(LogRec):
    KIND: ClassVar[str] = "unlock"
    what: str
    secs: float = 0.0


@record
class VendorError(LogRec):
    KIND: ClassVar[str] = "vendor_error"
    node: str
    reason: str
    lane: str = ""
    model: str = ""
    until: float | None = None
    error: str = ""
    started_t: float | None = None  # the call's boundaries as the process saw them: when it began, ended, first printed a provider
    ended_t: float | None = None  # error line, last printed anything, and was stopped
    first_error_t: float | None = None
    last_event_t: float | None = None
    kill_t: float | None = None
    error_observed: bool = False


@record
class Kill(LogRec):
    KIND: ClassVar[str] = "kill"
    what: str
    why: str
    secs: float = 0.0
    exit: int | None = None
    alive: list[int] = field(default_factory=list)  # pids that outlived every signal
    started_t: float | None = None
    ended_t: float | None = None
    first_error_t: float | None = None
    last_event_t: float | None = None  # the last activity seen before the stop, frozen before the signal
    kill_t: float | None = None
    observed_t: float | None = None


@record
class Overrun(LogRec):
    """A call that used its wall-time budget (the reviewer's) and was stopped through delegate; the loop goes on with the next rung."""

    KIND: ClassVar[str] = "overrun"
    stage: str
    budget_s: float
    elapsed_s: float
    lane: str = ""


@record
class RetryDecision(LogRec):
    """What the RetryPlan decided about a stopped call, with the facts it decided on."""

    KIND: ClassVar[str] = "retry_decision"
    step: str
    plan: str  # the RetryPlan row (worker_failed, lane_poll, crash, ...) or "" for a decision no row governs
    action: str  # retry | wait | new_thread | reroute | pause | ask | fault
    attempt: int = 0
    reason: str = ""
    timeout_s: float | None = None
    exit: int | None = None
    lane: str = ""
    evidence: str = ""


@record
class Transition(LogRec):
    KIND: ClassVar[str] = "transition"
    from_id: str = field(metadata={"name": "from"})
    to: str
    cause: str
    detail: str = ""


@record
class Reload(LogRec):
    KIND: ClassVar[str] = "reload"
    old: str
    new: str
    step: str


@record
class Warn(LogRec):
    KIND: ClassVar[str] = "warn"
    text: str


@record
class Note(LogRec):
    KIND: ClassVar[str] = "note"
    text: str


@record
class Close(LogRec):
    KIND: ClassVar[str] = "close"
    outcome: Outcome
    why_code: WhyCode | None = None
    sha: str = ""
    why: str = ""


EngineLog = (RunStart | StepStart | StepEnd | CallStart | CallEnd | CmdStart | CmdEnd | CheckStart | CheckEnd | GateStart | GateEnd
             | LandTry | WaitStart | WaitEnd | Lock | Unlock | VendorError | Kill | Overrun | RetryDecision | Transition
             | Reload | Checks | Warn | Note | Close)
ENGINE_LOG = table_of(RunStart, StepStart, StepEnd, CallStart, CallEnd, CmdStart, CmdEnd, CheckStart, CheckEnd, GateStart,
                      GateEnd, LandTry, WaitStart, WaitEnd, Lock, Unlock, VendorError, Kill, Overrun, RetryDecision, Transition,
                      Reload, Checks, Warn, Note, Close)


def decode(data: object) -> EngineLog:
    """The engine-log record `data` is; CodecError (StaleRecord for a foreign v) otherwise."""
    return from_tagged(ENGINE_LOG, data)
