"""Engine decisions after delegate has exhausted its worker retries and write reroute.

The pure policy maps stop facts to NewThread, Reroute, Yield or Fail. Fixed rows
carry outcome kinds; functions handle the remaining context-dependent recovery.
Delegate owns worker retries and thread recovery; the engine handles secret
false positives. Delegate crashes fail immediately and network stops pause.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, get_args

from taskloop.domain.lanes.retry import PLAN, RetryPlan
from tlkernel.delegate import REASON_TIMEOUT, DelegateResult, Permanence, RetryKind, Scope
from tlkernel.pausereasons import Producer

SCOPES: Final[tuple[Scope, ...]] = get_args(Scope)
PERMANENCES: Final[tuple[Permanence, ...]] = get_args(Permanence)
RETRY_KINDS: Final[tuple[RetryKind, ...]] = get_args(RetryKind)


@dataclass(frozen=True)
class Stop:
    """The stopped-call facts still read by engine policy, logging and pause wording."""

    scope: str
    permanence: str
    retry_kind: str = "none"
    retry_at: float = 0.0  # epoch the lane is predicted back, or the suggested poll gap (0: none given)
    reason: str = ""  # wording only
    lane: str = ""
    model: str = ""
    signal: int = 0  # the signal that ended the call (killed), 0 for none
    fix: str = ""
    exit_code: int | None = None  # the worker's exit status (negative: ended by that signal)
    timed_out: bool = False  # the engine or delegate ended the call at its time limit
    producer: Producer = "delegate"


def stop_of(res: DelegateResult) -> Stop | None:
    """The engine facts of a stopped result (None for a done call). A `killed`
    stop is a signal (contract 4 states no signal number, and (machine, transient, none) alone cannot tell it from a crash)."""
    st = res.stop
    if st is None:
        return None
    return Stop(
        st.scope,
        st.permanence,
        st.retry.kind,
        float(st.retry.at or 0.0),
        st.reason,
        res.account or "",
        res.model or "",
        1 if st.reason == "killed" else 0,
        st.fix,
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
    """Recovery state the executor has counted for this step."""

    attempt: int = 0
    denied_retried: bool = False
    secret_fp: bool = False  # the denial was `secrets` on a heredoc body that names .env (denials.secret_false_positive)
    node: str = ""


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
    """The run pauses; the bead stays open. retry_after is an epoch hint (0: none)."""

    kind: str
    retry_after: float = 0.0


@dataclass(frozen=True)
class Fail:
    kind: str
    plan: str = ""


Action = NewThread | Reroute | Yield | Fail


def _excluded(stop: Stop) -> str:
    return stop.lane if stop.scope == "account" or not stop.model else stop.model


def _machine_none(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """A delegate crash fails immediately; a signal still pauses the run."""
    if stop.signal:
        return Yield("PAUSE_KILLED")
    return Fail("FAULT_CRASHED")


def _bead_owner(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """secrets: a heredoc body that merely names .env gets one fresh thread told to use apply_patch (2.14), a second denial is a
    fault, and a real secret path is never retried. Never an ask."""
    if ctx.secret_fp and plan.left("denied_secret", int(ctx.denied_retried)):
        return NewThread("apply_patch", "denied_retried", "denied_secret")
    return Fail("FAULT_DENIED", "denied_secret")


def _bead_none(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """Delegate exhausted recovery. Hurt writes ask; other worker failures fault."""
    hurt = stop.timed_out or stop.exit_code == -15
    if hurt and ctx.node == "write" and plan.row("worker_failed").then == "ask":
        return Fail("ASK_STUCK", "worker_failed")
    return Fail("FAULT_INFRA", "worker_failed")


def _lane_predicted(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """Delegate exhausted its short waits; park the call."""
    return Yield("PAUSE_LANE", stop.retry_at)


def _lane_poll(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """Delegate exhausted its polls; try another lane."""
    return Reroute(_excluded(stop))


def _lane_none(stop: Stop, ctx: Ctx, plan: RetryPlan) -> Action:
    """A lane or model transient with no time: one other pick, then a pause."""
    if ctx.attempt < 2:
        return Reroute(_excluded(stop))
    return Yield("PAUSE_LANE")


# The table. Every legal tuple has a row; a new reason is a delegate classifier line, never a row here.
# Fixed rows are (outcome kind, whether to copy the predicted retry time).
Row = tuple[str, bool] | Callable[[Stop, Ctx, RetryPlan], Action]
TABLE: Final[dict[tuple[str, str, str], Row]] = {
    ("machine", "transient", "poll"): ("PAUSE_NETWORK", False),
    ("machine", "transient", "predicted"): ("PAUSE_LANE", True),
    ("machine", "transient", "none"): _machine_none,
    ("machine", "needs_owner", "none"): ("PAUSE_LANE", False),
    ("caller", "needs_owner", "none"): ("FAULT_BAD_REQUEST", False),
    ("caller", "transient", "none"): ("FAULT_BAD_REQUEST", False),  # no doc row: a caller's request does not heal by waiting
    ("caller", "transient", "predicted"): ("FAULT_BAD_REQUEST", False),  # no doc row
    ("caller", "transient", "poll"): ("FAULT_BAD_REQUEST", False),  # no doc row
    ("bead", "needs_owner", "none"): _bead_owner,
    ("bead", "transient", "none"): _bead_none,
    ("bead", "transient", "predicted"): _bead_none,  # the bead's own failure after delegate recovery
    ("bead", "transient", "poll"): ("PAUSE_LANE", False),
    ("account", "needs_owner", "none"): ("PAUSE_LANE", False),
    ("model", "needs_owner", "none"): ("PAUSE_LANE", False),
    ("account", "transient", "predicted"): _lane_predicted,
    ("model", "transient", "predicted"): _lane_predicted,
    ("account", "transient", "poll"): _lane_poll,
    ("model", "transient", "poll"): _lane_poll,
    ("account", "transient", "none"): _lane_none,
    ("model", "transient", "none"): _lane_none,
}

# The executable grid is checked against the vendored contract, including its reason facts.
LEGAL: Final = tuple(TABLE)


def decide(stop: Stop, ctx: Ctx, plan: RetryPlan = PLAN) -> Action:
    """The next Action for a stopped call. A signal on a machine stop is a kill (checkpoint kept, never a fail, never an
    ask). An unknown tuple pauses the lane: the contract may grow, the loop never fails or asks on what it cannot read."""
    if stop.signal and stop.scope == "machine":
        return Yield("PAUSE_KILLED")
    row = TABLE.get((stop.scope, stop.permanence, stop.retry_kind))
    if row is None:
        return Yield("PAUSE_LANE")
    if callable(row):
        return row(stop, ctx, plan)
    kind, predicted = row
    return Fail(kind) if kind.startswith("FAULT_") else Yield(kind, stop.retry_at if predicted else 0.0)
