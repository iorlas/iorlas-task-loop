"""Engine decisions after delegate has exhausted its worker retries and write reroute.

The pure policy maps stop facts to NewThread, Reroute, Yield or Fail. Only resumed
calls retain the engine's fresh-prompt recovery; delegate crashes fail immediately.
Network stops pause without charging a retry or marking a lane out.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, get_args

from taskloop.domain.lanes.pause_reasons import Producer
from taskloop.domain.lanes.retry import PLAN, RetryPlan
from tlkernel.delegate import REASON_TIMEOUT, DelegateResult, Permanence, RetryKind, Scope

SCOPES: Final[tuple[Scope, ...]] = get_args(Scope)
PERMANENCES: Final[tuple[Permanence, ...]] = get_args(Permanence)
RETRY_KINDS: Final[tuple[RetryKind, ...]] = get_args(RetryKind)

# Engine scheduling policy; these knobs are not fields or defaults in delegate's schema.
KNOBS: Final = {
    "net_wait_cap_s": 600,  # the lander waits this long for its git push network retry
}


@dataclass(frozen=True)
class Stop:
    """The facts of one stopped call (the contract's `stop{}` plus `run.ref`). Built by delegate_link from the answer."""

    scope: str
    permanence: str
    retry_kind: str = "none"
    retry_at: float = 0.0  # epoch the lane is predicted back, or the suggested poll gap (0: none given)
    reason: str = ""  # wording only
    resumable: bool = False
    partial: bool = False  # work was seen before the stop
    ref: str = ""  # the vendor session of the call ("" when it never got one)
    lane: str = ""
    model: str = ""
    signal: int = 0  # the signal that ended the call (killed), 0 for none
    fix: str = ""
    fingerprint: str = ""
    exit_code: int | None = None  # the worker's exit status (negative: ended by that signal)
    timed_out: bool = False  # the engine or delegate ended the call at its time limit
    producer: Producer = "delegate"


def stop_of(res: DelegateResult) -> Stop | None:
    """The `Stop` of a result that stopped (None for a done call): the answer's `stop{}` facts plus what its worker did. A `killed`
    stop is a signal (contract 4 states no signal number, and (machine, transient, none) alone cannot tell it from a crash)."""
    st = res.stop
    if st is None:
        return None
    ref = st.ref or res.ref or (res.usage.ref if res.usage and res.usage.ref else "")
    return Stop(
        st.scope,
        st.permanence,
        st.retry.kind,
        float(st.retry.at or 0.0),
        st.reason,
        st.resumable,
        st.partial,
        ref,
        res.lane or "",
        res.model or "",
        1 if st.reason == "killed" else 0,
        st.fix,
        "",
        res.exit_code,
        st.reason == REASON_TIMEOUT,
        st.producer,
    )


NETWORK: Final = ("machine", "transient", "poll")


def net_data(res: DelegateResult) -> bool:
    """A network stop that saw work and carries data: the worker may have finished before the connection broke. Data that passes the
    node's schema is the answer (done), data that does not is kept for `attach`."""
    st = res.stop
    return st is not None and st.partial and res.data is not None and (st.scope, st.permanence, st.retry.kind) == NETWORK


@dataclass(frozen=True)
class Ctx:
    """What the executor has counted for this step. now: the Clock's wall time."""

    now: float
    resumed: bool = False  # this call resumed a vendor thread
    attempt: int = 0
    denied_retried: bool = False
    secret_fp: bool = False  # the denial was `secrets` on a heredoc body that names .env (denials.secret_false_positive)
    node: str = ""
    resume_refused: int = 0  # resumed calls the vendor refused, each answered with one new thread


@dataclass(frozen=True)
class NewThread:
    note: str = ""
    charges: str = "attempt"
    plan: str = ""


@dataclass(frozen=True)
class Reroute:
    exclude: str  # lane or model the next pick must not use
    charges: str = "attempt"
    plan: str = ""


@dataclass(frozen=True)
class Yield:
    """The run pauses with a wake; the bead stays open. retry_after: epoch hint (0: none). banner: say it once."""

    kind: str  # the outcome.Kind name (PAUSE_LANE, PAUSE_NETWORK, PAUSE_KILLED)
    say: str = ""
    retry_after: float = 0.0
    fix: str = ""
    banner: bool = False
    charges: str = ""


@dataclass(frozen=True)
class Fail:
    kind: str  # the outcome.Kind name (FAULT_*, or ASK_STUCK for the one ask a failing worker gets)
    say: str = ""
    charges: str = ""
    plan: str = ""


Action = NewThread | Reroute | Yield | Fail
Knobs = Mapping[str, float]


def _say(stop: Stop) -> str:
    return (f"{stop.reason} {stop.fix}").strip() or f"{stop.scope}/{stop.permanence}/{stop.retry_kind}"


def _yield(kind: str, stop: Stop, retry_after: float = 0.0, banner: bool = False) -> Yield:
    return Yield(kind, _say(stop), retry_after, stop.fix, banner)


def _fail(kind: str, stop: Stop, plan: str = "") -> Fail:
    return Fail(kind, _say(stop), plan=plan)


def _excluded(stop: Stop) -> str:
    return stop.lane if stop.scope == "lane" or not stop.model else stop.model


def _machine_predicted(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    return _yield("PAUSE_LANE", stop, stop.retry_at)


def _machine_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """A delegate crash fails immediately; a signal still pauses the run."""
    if stop.signal:
        return _yield("PAUSE_KILLED", stop)
    return _fail("FAULT_CRASHED", stop)


def _machine_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """setup, contract violations, no lane and no time: the machine's owner fixes it; the loop never asks per bead."""
    if stop.signal:
        return _yield("PAUSE_KILLED", stop)
    return _yield("PAUSE_LANE", stop)


def _caller_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """bad_request, caller (an unknown ref): the call itself is wrong. When it resumed a thread, the vendor may have refused that ref:
    once on a new thread with the whole prompt, then the fault."""
    if ctx.resumed and plan.left("resume_refused", ctx.resume_refused):
        return NewThread("", "resume_refused", "resume_refused")
    return _caller(stop, ctx, cfg, plan)


def _caller(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    return _fail("FAULT_BAD_REQUEST", stop)


def _bead_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """secrets: a heredoc body that merely names .env gets one fresh thread told to use apply_patch (2.14), a second denial is a
    fault, and a real secret path is never retried. Never an ask."""
    if ctx.secret_fp and plan.left("denied_secret", int(ctx.denied_retried)):
        return NewThread("apply_patch", "denied_retried", "denied_secret")
    return _fail("FAULT_DENIED", stop, "denied_secret")


def _bead_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """Delegate exhausted recovery. Only resumed calls need a fresh engine prompt first."""
    hurt = stop.timed_out or stop.exit_code == -15
    if ctx.resumed and plan.left("worker_failed", ctx.attempt):
        if hurt and ctx.node == "write":
            return Reroute(_excluded(stop), "attempt", "worker_failed")
        return NewThread("", "attempt", "worker_failed")
    if hurt and ctx.node == "write" and plan.row("worker_failed").then == "ask":
        return Fail("ASK_STUCK", _say(stop), plan="worker_failed")
    return _fail("FAULT_INFRA", stop, "worker_failed")


def _bead_poll(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    return _yield("PAUSE_LANE", stop)


def _lane_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """logged_out, credit_exhausted, model unsupported: the lane (or model) waits for its owner; the loop does not ask."""
    return _yield("PAUSE_LANE", stop)


def _lane_predicted(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """Delegate exhausted its short waits; park fresh calls and move resumed threads."""
    if ctx.resumed:
        return NewThread("lane_out")
    return _yield("PAUSE_LANE", stop, stop.retry_at)


def _lane_poll(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """Delegate exhausted its polls; try another lane."""
    return NewThread("lane_out") if ctx.resumed else Reroute(_excluded(stop))


def _lane_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """A lane or model transient with no time: one other pick, then a pause."""
    if ctx.attempt < 2:
        return Reroute(_excluded(stop))
    return _yield("PAUSE_LANE", stop)


# The table. Every legal tuple has a row; a new reason is a delegate classifier line, never a row here.
TABLE: Final[dict[tuple[str, str, str], Callable[[Stop, Ctx, Knobs, RetryPlan], Action]]] = {
    ("machine", "transient", "poll"): lambda stop, ctx, cfg, plan: _yield("PAUSE_NETWORK", stop),
    ("machine", "transient", "predicted"): _machine_predicted,
    ("machine", "transient", "none"): _machine_none,
    ("machine", "needs_owner", "none"): _machine_owner,
    ("caller", "needs_owner", "none"): _caller_owner,
    ("caller", "transient", "none"): _caller,  # no doc row: a caller's request does not heal by waiting
    ("caller", "transient", "predicted"): _caller,  # no doc row
    ("caller", "transient", "poll"): _caller,  # no doc row
    ("bead", "needs_owner", "none"): _bead_owner,
    ("bead", "transient", "none"): _bead_none,
    ("bead", "transient", "predicted"): _bead_none,  # no doc row: the bead's own failure, tried once more
    ("bead", "transient", "poll"): _bead_poll,
    ("lane", "needs_owner", "none"): _lane_owner,
    ("model", "needs_owner", "none"): _lane_owner,
    ("lane", "transient", "predicted"): _lane_predicted,
    ("model", "transient", "predicted"): _lane_predicted,
    ("lane", "transient", "poll"): _lane_poll,
    ("model", "transient", "poll"): _lane_poll,
    ("lane", "transient", "none"): _lane_none,
    ("model", "transient", "none"): _lane_none,
}

# The executable grid is checked against the vendored contract, including its reason facts.
LEGAL: Final = tuple(TABLE)


def decide(stop: Stop, ctx: Ctx, cfg: Knobs = KNOBS, plan: RetryPlan = PLAN) -> Action:
    """The next Action for a stopped call. A signal on a machine stop is a kill (checkpoint kept, never a fail, never an
    ask). An unknown tuple pauses the lane: the contract may grow, the loop never fails or asks on what it cannot read."""
    if stop.signal and stop.scope == "machine":
        return _yield("PAUSE_KILLED", stop)
    row = TABLE.get((stop.scope, stop.permanence, stop.retry_kind))
    if row is None:
        return _yield("PAUSE_LANE", stop)
    return row(stop, ctx, cfg, plan)
