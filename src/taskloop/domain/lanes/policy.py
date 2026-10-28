"""The lane decision: what to do next after one delegate call stopped. One pure function over the stop's facts.

`decide(stop, ctx, cfg, plan)` has no sleep, no git, no bd and no IO. The key is (scope, permanence, retry_kind), A3's facts;
`stop.reason` is wording; the one place it is read is `worker_failed` (a timeout or a -15 exit gets another lane first). The output is one
of seven Actions (61-integration sec 5.5): Retry | Wait | WaitNet | NewThread | Reroute | Yield | Fail. A Yield or Fail names the
outcome Kind by its name (the app maps it); every retry count is a row of `retry.PLAN`.

A network stop charges nothing: not `attempt`, not `crashes`, not `polls`, not `waited_lane_s`, no ask, replan or storm
counter, and it never marks a lane out (the delegate holds lane truth).
Design: 60-design-A1 sec 2.2, 60-design-A3 sec 2.2, 61-integration sec 5.5.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.delegate import REASON_TIMEOUT, DelegateResult
from taskloop.domain.lanes.retry import PLAN, RetryPlan

SCOPES: Final = ("bead", "caller", "model", "lane", "machine")
PERMANENCES: Final = ("transient", "needs_owner")
RETRY_KINDS: Final = ("none", "predicted", "poll")

# The 20 legal tuples: needs_owner is always retry none (5), transient takes every retry kind (15).
LEGAL: Final = tuple([(s, "needs_owner", "none") for s in SCOPES] + [(s, "transient", k) for s in SCOPES for k in RETRY_KINDS])

KNOBS: Final = {
    "wait_cap_s": 180,  # a lane back sooner than this is waited for in-process; later it is a PAUSE_LANE with a wake time
    "net_wait_cap_s": 600,  # one call waits this long for the network, then yields PAUSE_NETWORK
    "net_probe_up_stops": 3,  # network stops while the probe said up, inside net_probe_window_s: a proxy or DNS fault
    "net_probe_window_s": 300,
    "net_pause_s": 1800,  # that pause; doubles with each further such stop
    "net_pause_max_s": 21600,
    "poll_s": 20,  # the wait of a poll when the stop names none
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


def stop_of(res: DelegateResult) -> Stop | None:
    """The `Stop` of a result that stopped (None for a done call): the answer's `stop{}` facts plus what its worker did. A `killed`
    stop is a signal (contract 3 states no signal number, and (machine, transient, none) alone cannot tell it from a crash)."""
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
    )


@dataclass(frozen=True)
class Ctx:
    """What the executor has counted for this step. now: the Clock's wall time."""

    now: float
    resumed: bool = False  # this call resumed a vendor thread
    attempt: int = 0
    polls: int = 0
    crashes: int = 0
    waited_lane_s: float = 0.0
    waited_net_s: float = 0.0
    net_up_stops: int = 0  # network stops in the last net_probe_window_s whose probe said up
    denied_retried: bool = False
    secret_fp: bool = False  # the denial was `secrets` on a heredoc body that names .env (denials.secret_false_positive)
    node: str = ""


@dataclass(frozen=True)
class Retry:
    not_before: float  # epoch; the executor sleeps until then
    resume: str = ""  # vendor ref to resume ("" = a new thread)
    charges: str = "attempt"  # the Ctx counter this action raises
    plan: str = ""  # the RetryPlan row this retry belongs to


@dataclass(frozen=True)
class Wait:
    until: float
    resume: str = ""
    charges: str = "waited_lane_s"
    plan: str = ""


@dataclass(frozen=True)
class WaitNet:
    resume: str  # the ref to resume once the probe passes ("" = a new thread)
    max_s: float  # most this call may still wait for the network
    charges: str = ""


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


Action = Retry | Wait | WaitNet | NewThread | Reroute | Yield | Fail
Knobs = Mapping[str, float]


def _say(stop: Stop) -> str:
    return (f"{stop.reason} {stop.fix}").strip() or f"{stop.scope}/{stop.permanence}/{stop.retry_kind}"


def _yield(kind: str, stop: Stop, retry_after: float = 0.0, banner: bool = False) -> Yield:
    return Yield(kind, _say(stop), retry_after, stop.fix, banner)


def _fail(kind: str, stop: Stop, plan: str = "") -> Fail:
    return Fail(kind, _say(stop), plan=plan)


def _excluded(stop: Stop) -> str:
    return stop.lane if stop.scope == "lane" or not stop.model else stop.model


def _network(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """machine, transient, poll: the network (or a lock) is the machine's. Resume the same thread when the probe passes."""
    if ctx.net_up_stops >= cfg["net_probe_up_stops"]:  # the probe says up and the calls say down: visible, never silent
        over = ctx.net_up_stops - cfg["net_probe_up_stops"]
        return _yield("PAUSE_NETWORK", stop, ctx.now + min(cfg["net_pause_s"] * (2**over), cfg["net_pause_max_s"]), True)
    left = cfg["net_wait_cap_s"] - ctx.waited_net_s
    if left <= 0:
        return _yield("PAUSE_NETWORK", stop)
    return WaitNet(stop.ref if (ctx.resumed or stop.ref) else "", left)


def _machine_predicted(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    return _yield("PAUSE_LANE", stop, stop.retry_at)


def _machine_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """A crash of delegate itself: again as a fresh call after each rest, then a fault. Never an ask."""
    if stop.signal:
        return _yield("PAUSE_KILLED", stop)
    if plan.left("crash", ctx.crashes):
        return Retry(ctx.now + plan.rest("crash", ctx.crashes), "", "crashes", "crash")
    return _fail("FAULT_CRASHED", stop, "crash")


def _machine_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """setup, contract violations, no lane and no time: the machine's owner fixes it; the loop never asks per bead."""
    if stop.signal:
        return _yield("PAUSE_KILLED", stop)
    return _yield("PAUSE_LANE", stop)


def _caller(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    return _fail("FAULT_BAD_REQUEST", stop)


def _bead_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """secrets: a heredoc body that merely names .env gets one fresh thread told to use apply_patch (2.14), a second denial is a
    fault, and a real secret path is never retried. Never an ask."""
    if ctx.secret_fp and plan.left("denied_secret", int(ctx.denied_retried)):
        return NewThread("apply_patch", "denied_retried", "denied_secret")
    return _fail("FAULT_DENIED", stop, "denied_secret")


def _bead_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """worker_failed, schema_invalid, timeout: once more, then a fault. A write that timed out or whose lane exited -15 moves to
    another lane for that retry and, when it is spent, raises one ask (never an unexplained end)."""
    hurt = stop.timed_out or stop.exit_code == -15
    if plan.left("worker_failed", ctx.attempt):
        if hurt and ctx.node == "write":
            return Reroute(_excluded(stop), "attempt", "worker_failed")
        if stop.resumable and stop.ref:
            return Retry(ctx.now, stop.ref, "attempt", "worker_failed")
        return NewThread("", "attempt", "worker_failed")
    if hurt and ctx.node == "write" and plan.row("worker_failed").then == "ask":
        return Fail("ASK_STUCK", _say(stop), plan="worker_failed")
    return _fail("FAULT_INFRA", stop, "worker_failed")


def _poll_wait(stop: Stop, ctx: Ctx, cfg: Knobs) -> float:
    return ctx.now + (stop.retry_at if 0 < stop.retry_at <= cfg["wait_cap_s"] else cfg["poll_s"])


def _bead_poll(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """duplicate_task: a few polls, then the bead pauses."""
    if plan.left("lane_poll", ctx.polls):
        return Wait(_poll_wait(stop, ctx, cfg), stop.ref if stop.resumable else "", "polls", "lane_poll")
    return _yield("PAUSE_LANE", stop)


def _lane_owner(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """logged_out, credit_exhausted, model unsupported: the lane (or model) waits for its owner; the loop does not ask."""
    return _yield("PAUSE_LANE", stop)


def _lane_predicted(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """rate_limited, held, hung: wait for it inside the cap, else pause with the time. A resumed thread moves at once."""
    if ctx.resumed:
        return NewThread("lane_out")
    gap = stop.retry_at - ctx.now
    if stop.retry_at and gap <= cfg["wait_cap_s"] - ctx.waited_lane_s:
        return Wait(stop.retry_at, "", "waited_lane_s")
    return _yield("PAUSE_LANE", stop, stop.retry_at)


def _lane_poll(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """busy, vendor_blip: a few polls, then another lane (a resumed thread starts fresh there)."""
    if plan.left("lane_poll", ctx.polls):
        return Wait(_poll_wait(stop, ctx, cfg), stop.ref if (ctx.resumed and stop.resumable) else "", "polls", "lane_poll")
    return NewThread("lane_out") if ctx.resumed else Reroute(_excluded(stop))


def _lane_none(stop: Stop, ctx: Ctx, cfg: Knobs, plan: RetryPlan) -> Action:
    """A lane or model transient with no time: one other pick, then a pause."""
    if ctx.attempt < 2:
        return Reroute(_excluded(stop))
    return _yield("PAUSE_LANE", stop)


# The table. Every legal tuple has a row; a new reason is a delegate classifier line, never a row here.
TABLE: Final[dict[tuple[str, str, str], Callable[[Stop, Ctx, Knobs, RetryPlan], Action]]] = {
    ("machine", "transient", "poll"): _network,
    ("machine", "transient", "predicted"): _machine_predicted,
    ("machine", "transient", "none"): _machine_none,
    ("machine", "needs_owner", "none"): _machine_owner,
    ("caller", "needs_owner", "none"): _caller,
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


def decide(stop: Stop, ctx: Ctx, cfg: Knobs = KNOBS, plan: RetryPlan = PLAN) -> Action:
    """The next Action for a stopped call. A signal on a machine stop is a kill (checkpoint kept, never a fail, never an
    ask). An unknown tuple pauses the lane: the contract may grow, the loop never fails or asks on what it cannot read."""
    if stop.signal and stop.scope == "machine":
        return _yield("PAUSE_KILLED", stop)
    row = TABLE.get((stop.scope, stop.permanence, stop.retry_kind))
    if row is None:
        return _yield("PAUSE_LANE", stop)
    return row(stop, ctx, cfg, plan)
