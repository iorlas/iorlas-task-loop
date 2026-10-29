"""EngineLog: the union of records an engine run appends to engine/<run>.jsonl (v2). Start/end pairs share an `id`, unique
within the file; an end without its start, or the reverse, is a run that died in between."""
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from taskloop.contracts.checks import CheckRun
from taskloop.contracts.enums import Outcome, WaitWhat, WhyCode
from taskloop.contracts.trace import Tokens
from taskloop.contracts.wire import Rec, load


class LogRec(Rec):
    V: ClassVar[int] = 2
    kind: str = ""  # each member narrows it to its tag; declared here so `kind` is written right after `v`
    t: float = 0.0  # unset (0): RunLog.emit stamps the time of the append


class RunStart(LogRec):
    kind: Literal["run_start"] = "run_start"
    run: str
    bead: str
    worktree: str
    slot: str | None = None
    prev_run: str = ""
    started_because: str = ""
    ask: str = ""
    branch: str = ""  # the task branch the run works on ("" when HEAD is detached)


class StepStart(LogRec):
    kind: Literal["step_start"] = "step_start"
    id: str
    step: str
    text: str = ""
    stage: int | None = None
    stages: int | None = None
    round: int | None = None
    write: int | None = None
    fix: int | None = None


class StepEnd(LogRec):
    kind: Literal["step_end"] = "step_end"
    id: str
    step: str
    outcome: str
    detail: str = ""
    secs: float = 0.0


class CallStart(LogRec):
    kind: Literal["call_start"] = "call_start"
    id: str
    n: int
    step: str
    node: str
    role: str
    resume: bool = False


class CallEnd(LogRec):
    kind: Literal["call_end"] = "call_end"
    id: str
    status: str
    reason: str | None = None
    ref: str = ""
    lane: str = ""
    model: str = ""
    effort: str = ""
    secs: float = 0.0
    tokens: Tokens = Field(default_factory=Tokens)
    cost: float = 0.0
    family: str = ""
    flag: str | None = None
    transcript: str = ""
    exit: int | None = None  # the worker's exit code (delegate's answer `exit_code`; negative: ended by that signal)


class CmdStart(LogRec):
    kind: Literal["cmd_start"] = "cmd_start"
    id: str
    text: str
    cwd: str = ""


class CmdEnd(LogRec):
    kind: Literal["cmd_end"] = "cmd_end"
    id: str
    exit: int
    secs: float = 0.0
    out: str = ""


class CheckStart(LogRec):
    kind: Literal["check_start"] = "check_start"
    id: str
    check: str
    group: str
    cmd: str
    round: int
    log: str = ""
    timeout_s: float | None = None


class CheckEnd(LogRec):
    kind: Literal["check_end"] = "check_end"
    id: str
    exit: int | None
    status: str
    tries: int = 1
    secs: float = 0.0
    wall_hit: bool = False  # the engine stopped it at its wall limit (start: the CheckStart of the same id; end: this record's t)


class GateStart(LogRec):
    kind: Literal["gate_start"] = "gate_start"
    cmd: str
    log: str = ""
    tree: str = ""


class GateEnd(LogRec):
    kind: Literal["gate_end"] = "gate_end"
    exit: int | None
    secs: float = 0.0
    skipped: bool = False


class LandTry(LogRec):
    """One try of the land: what main was before the fetch and after it, whether the rebase moved the branch, and the recipe that failed."""

    kind: Literal["land_try"] = "land_try"
    n: int
    base_before: str = ""
    base_after: str = ""
    rebase_moved: bool = False
    failing: str = ""  # "gate", "conflict" or "verify": a fix round; "stale": main moved under the outside gate; "": on to the push
    gate: str = ""  # where the gate ran: "outside" the lock, "inside" it, "cached" (passed on this tree and base before); "" none


class WaitStart(LogRec):
    kind: Literal["wait_start"] = "wait_start"
    id: str
    what: WaitWhat
    holder: str = ""
    until: float | None = None


class WaitEnd(LogRec):
    kind: Literal["wait_end"] = "wait_end"
    id: str
    secs: float
    in_budget: bool = False


class Checks(LogRec):
    """One round of checks: the CheckRun (every check with its result, and what the round's cache saved)."""
    kind: Literal["checks"] = "checks"
    node_id: str
    run: CheckRun


class Lock(LogRec):
    kind: Literal["lock"] = "lock"
    what: str
    holder: str = ""


class Unlock(LogRec):
    kind: Literal["unlock"] = "unlock"
    what: str
    secs: float = 0.0


class VendorError(LogRec):
    kind: Literal["vendor_error"] = "vendor_error"
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


class Kill(LogRec):
    kind: Literal["kill"] = "kill"
    what: str
    why: str
    secs: float = 0.0
    exit: int | None = None
    alive: list[int] = Field(default_factory=list)  # pids that outlived every signal
    started_t: float | None = None
    ended_t: float | None = None
    first_error_t: float | None = None
    last_event_t: float | None = None  # the last activity seen before the stop, frozen before the signal
    kill_t: float | None = None
    observed_t: float | None = None


class Overrun(LogRec):
    """A call that used its wall-time budget (the reviewer's) and was stopped through delegate; the loop goes on with the next rung."""

    kind: Literal["overrun"] = "overrun"
    stage: str
    budget_s: float
    elapsed_s: float
    lane: str = ""


class RetryDecision(LogRec):
    """What the RetryPlan decided about a stopped call, with the facts it decided on."""

    kind: Literal["retry_decision"] = "retry_decision"
    step: str
    plan: str  # the RetryPlan row (worker_failed, lane_poll, crash, ...) or "" for a decision no row governs
    action: str  # retry | wait | new_thread | reroute | pause | ask | fault
    attempt: int = 0
    reason: str = ""
    timeout_s: float | None = None
    exit: int | None = None
    lane: str = ""
    evidence: str = ""


class Transition(LogRec):
    kind: Literal["transition"] = "transition"
    from_id: str = Field(alias="from")
    to: str
    cause: str
    detail: str = ""


class Reload(LogRec):
    kind: Literal["reload"] = "reload"
    old: str
    new: str
    step: str


class Artifacts(LogRec):
    """The files ingest copied into the bead's artifact directory when a step ended (one record per ingest that copied something)."""

    kind: Literal["artifacts"] = "artifacts"
    id: str  # the step that produced them
    step: str
    bead: str
    names: list[str] = Field(default_factory=list)


class Warn(LogRec):
    kind: Literal["warn"] = "warn"
    text: str


class Note(LogRec):
    kind: Literal["note"] = "note"
    text: str


class Said(LogRec):
    """One comment the engine posted on the bead (Engine.comment, the one poster), tied to the step that was open."""

    kind: Literal["said"] = "said"
    step: str  # the id of the open step (StepStart.id), "" when none was open
    who: str  # engine, or owner for an owner's note the run passed on
    text: str


class Assumed(LogRec):
    """What the planner could not decide or find and planned around instead of asking (tl-ntp)."""

    kind: Literal["assumed"] = "assumed"
    step: str  # the id of the open step
    text: str
    reversible: bool = True


StuckWhy = Literal["silent", "same_red"]


class Stuck(LogRec):
    """The run is stuck (domain/stuck.py decides, at the Beat tick): silent past its step's limit, or the same red checks
    runlife.SAME_RED rounds in a row. One record per episode; the episode ends with new activity or a different round."""

    kind: Literal["stuck"] = "stuck"
    why: StuckWhy
    step: str  # the name of the step it is stuck in ("" when none was open)
    since: float  # silent: the last activity; same_red: the first of the red rounds
    limit_s: float = 0.0  # silent: the step's limit
    sig: str = ""  # same_red: CheckRun.signature() of the rounds


class Beat(LogRec):
    """The proof of life: appended every runlife.BEAT_EVERY seconds while the run's process lives (it is what runlife.liveness reads)."""

    kind: Literal["beat"] = "beat"


class Close(LogRec):
    kind: Literal["close"] = "close"
    outcome: Outcome
    why_code: WhyCode | None = None
    sha: str = ""
    why: str = ""


EngineLog = Annotated[
    RunStart | StepStart | StepEnd | CallStart | CallEnd | CmdStart | CmdEnd | CheckStart | CheckEnd | GateStart | GateEnd | LandTry
    | WaitStart | WaitEnd | Lock | Unlock | VendorError | Kill | Overrun | RetryDecision | Transition | Reload | Checks | Artifacts
    | Warn | Note | Said | Assumed | Stuck | Beat | Close,
    Field(discriminator="kind"),
]


def decode(data: object) -> EngineLog:
    """The engine-log record `data` is; ValidationError (StaleRecord for a foreign v) otherwise."""
    return load(EngineLog, data)
