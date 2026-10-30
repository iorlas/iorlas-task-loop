"""EngineLog: the union of records an engine run appends to engine/<run>.jsonl (v2). Start/end pairs share an `id`, unique
within the file; an end without its start, or the reverse, is a run that died in between."""
from typing import ClassVar, Literal, final

import msgspec

from taskloop.contracts.checks import CheckRun
from taskloop.contracts.enums import Outcome, WaitWhat, WhyCode
from taskloop.contracts.trace import Tokens
from taskloop.contracts.wire import Tagged, load


class LogRec(Tagged, kw_only=True):
    V: ClassVar[int] = 2
    t: float = 0.0  # unset (0): RunLog.emit stamps the time of the append


@final
class RunStart(LogRec, tag="run_start"):
    run: str
    bead: str
    worktree: str
    slot: str | None = None
    prev_run: str = ""
    started_because: str = ""
    ask: str = ""
    branch: str = ""  # the task branch the run works on ("" when HEAD is detached)


@final
class StepStart(LogRec, tag="step_start"):
    id: str
    step: str
    text: str = ""
    stage: int | None = None
    stages: int | None = None
    round: int | None = None
    write: int | None = None
    fix: int | None = None


@final
class StepEnd(LogRec, tag="step_end"):
    id: str
    step: str
    outcome: str
    detail: str = ""
    secs: float = 0.0


@final
class CallStart(LogRec, tag="call_start"):
    id: str
    n: int
    step: str
    node: str
    role: str
    resume: bool = False


@final
class CallEnd(LogRec, tag="call_end"):
    id: str
    status: str
    reason: str | None = None
    ref: str = ""
    lane: str = ""
    model: str = ""
    effort: str = ""
    secs: float = 0.0
    tokens: Tokens = msgspec.field(default_factory=Tokens)
    cost: float = 0.0
    cost_source: str = ""  # delegate's usage.cost_source (harness, free, unknown); "" in a log written before it: cost 0 then is not known
    family: str = ""
    flag: str | None = None
    transcript: str = ""
    exit: int | None = None  # the worker's exit code (delegate's answer `exit_code`; negative: ended by that signal)


@final
class CmdStart(LogRec, tag="cmd_start"):
    id: str
    text: str
    cwd: str = ""


@final
class CmdEnd(LogRec, tag="cmd_end"):
    id: str
    exit: int
    secs: float = 0.0
    out: str = ""


@final
class CheckStart(LogRec, tag="check_start"):
    id: str
    check: str
    group: str
    cmd: str
    round: int
    log: str = ""
    timeout_s: float | None = None
    lane: str = ""


@final
class CheckEnd(LogRec, tag="check_end"):
    id: str
    exit: int | None
    status: str
    tries: int = 1
    secs: float = 0.0
    wall_hit: bool = False  # the engine stopped it at its wall limit (start: the CheckStart of the same id; end: this record's t)
    waited: float = 0.0  # seconds it queued for a machine-wide resource lease before it began
    lane: str = ""
    at: float = 0.0  # seconds after its block began that it started
    cancelled: bool = False  # another lane's red stopped it


@final
class GateStart(LogRec, tag="gate_start"):
    cmd: str
    log: str = ""
    tree: str = ""


@final
class GateEnd(LogRec, tag="gate_end"):
    exit: int | None
    secs: float = 0.0
    skipped: bool = False
    deferred: list[str] = msgspec.field(default_factory=list)  # checks passed over: the host lacks their resource, inputs unchanged


@final
class LandTry(LogRec, tag="land_try"):
    """One try of the land: what main was before the fetch and after it, whether the rebase moved the branch, and the recipe that failed."""

    n: int
    base_before: str = ""
    base_after: str = ""
    rebase_moved: bool = False
    failing: str = ""  # "gate", "conflict" or "verify": a fix round; "stale": main moved under the outside gate; "": on to the push
    gate: str = ""  # where the gate ran: "outside" the lock, "inside" it, "cached" (passed on this tree and base before); "" none


@final
class WaitStart(LogRec, tag="wait_start"):
    id: str
    what: WaitWhat
    holder: str = ""
    until: float | None = None


@final
class WaitEnd(LogRec, tag="wait_end"):
    id: str
    secs: float
    in_budget: bool = False


@final
class Checks(LogRec, tag="checks"):
    """One round of checks: the CheckRun (every check with its result, and what the round's cache saved)."""

    node_id: str
    run: CheckRun


@final
class Lock(LogRec, tag="lock"):
    what: str
    holder: str = ""


@final
class Unlock(LogRec, tag="unlock"):
    what: str
    secs: float = 0.0


@final
class VendorError(LogRec, tag="vendor_error"):
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


@final
class Kill(LogRec, tag="kill"):
    what: str
    why: str
    secs: float = 0.0
    exit: int | None = None
    alive: list[int] = msgspec.field(default_factory=list)  # pids that outlived every signal
    started_t: float | None = None
    ended_t: float | None = None
    first_error_t: float | None = None
    last_event_t: float | None = None  # the last activity seen before the stop, frozen before the signal
    kill_t: float | None = None
    observed_t: float | None = None


@final
class Overrun(LogRec, tag="overrun"):
    """A call that used its wall-time budget (the reviewer's) and was stopped through delegate; the loop goes on with the next rung."""

    stage: str
    budget_s: float
    elapsed_s: float
    lane: str = ""


@final
class RetryDecision(LogRec, tag="retry_decision"):
    """What the RetryPlan decided about a stopped call, with the facts it decided on."""

    step: str
    plan: str  # the RetryPlan row (worker_failed, lane_poll, crash, ...) or "" for a decision no row governs
    action: str  # retry | wait | new_thread | reroute | pause | ask | fault
    attempt: int = 0
    reason: str = ""
    timeout_s: float | None = None
    exit: int | None = None
    lane: str = ""
    evidence: str = ""


@final
class Transition(LogRec, tag="transition"):
    from_id: str = msgspec.field(name="from")
    to: str
    cause: str
    detail: str = ""


@final
class Reload(LogRec, tag="reload"):
    old: str
    new: str
    step: str


@final
class Artifacts(LogRec, tag="artifacts"):
    """The files ingest copied into the bead's artifact directory when a step ended (one record per ingest that copied something)."""

    id: str  # the step that produced them
    step: str
    bead: str
    names: list[str] = msgspec.field(default_factory=list)


@final
class Warn(LogRec, tag="warn"):
    text: str


@final
class Note(LogRec, tag="note"):
    text: str


@final
class Said(LogRec, tag="said"):
    """One comment the engine posted on the bead (Engine.comment, the one poster), tied to the step that was open."""

    step: str  # the id of the open step (StepStart.id), "" when none was open
    who: str  # engine, or owner for an owner's note the run passed on
    text: str


@final
class Assumed(LogRec, tag="assumed"):
    """What the planner could not decide or find and planned around instead of asking (tl-ntp)."""

    step: str  # the id of the open step
    text: str
    reversible: bool = True


StuckWhy = Literal["silent", "same_red"]


@final
class Stuck(LogRec, tag="stuck"):
    """The run is stuck (domain/stuck.py decides, at the Beat tick): silent past its step's limit, or the same red checks
    runlife.SAME_RED rounds in a row. One record per episode; the episode ends with new activity or a different round."""

    why: StuckWhy
    step: str  # the name of the step it is stuck in ("" when none was open)
    since: float  # silent: the last activity; same_red: the first of the red rounds
    limit_s: float = 0.0  # silent: the step's limit
    sig: str = ""  # same_red: CheckRun.signature() of the rounds


@final
class Beat(LogRec, tag="beat"):
    """The proof of life: appended every runlife.BEAT_EVERY seconds while the run's process lives (it is what runlife.liveness reads)."""


@final
class Close(LogRec, tag="close"):
    outcome: Outcome
    why_code: WhyCode | None = None
    sha: str = ""
    why: str = ""


EngineLog = (
    RunStart | StepStart | StepEnd | CallStart | CallEnd | CmdStart | CmdEnd | CheckStart | CheckEnd | GateStart | GateEnd | LandTry
    | WaitStart | WaitEnd | Lock | Unlock | VendorError | Kill | Overrun | RetryDecision | Transition | Reload | Checks | Artifacts
    | Warn | Note | Said | Assumed | Stuck | Beat | Close
)


def decode(data: object) -> EngineLog:
    """The engine-log record `data` is; msgspec.ValidationError (StaleRecord for a foreign v) otherwise."""
    return load(EngineLog, data)
