"""The lane decision: what to do next after one delegate call stopped. One pure function over the stop's facts.

`decide(stop, ctx, cfg)` has no sleep, no git, no bd and no IO. The key is (scope, permanence, retry_kind), A3's facts;
`stop.reason` is wording and is never read here. The output is one of seven Actions (61-integration sec 5.5):
Retry | Wait | WaitNet | NewThread | Reroute | Yield(RunOutcome) | Fail(RunOutcome). Nothing here asks the owner.

A network stop charges nothing: not `attempt`, not `crashes`, not `polls`, not `waited_lane_s`, no ask, replan or storm
counter, and it never marks a lane out (the delegate holds lane truth). Unused by the engine until R21.
Design: 60-design-A1 sec 2.2, 60-design-A3 sec 2.2, 61-integration sec 5.5. Python 3.8+, stdlib only; imports outcome only.
"""

from dataclasses import dataclass

import outcome as oc

SCOPES = ("bead", "caller", "model", "lane", "machine")
PERMANENCES = ("transient", "needs_owner")
RETRY_KINDS = ("none", "predicted", "poll")

# The 20 legal tuples: needs_owner is always retry none (5), transient takes every retry kind (15).
LEGAL = tuple([(s, "needs_owner", "none") for s in SCOPES] + [(s, "transient", k) for s in SCOPES for k in RETRY_KINDS])

KNOBS = {
    "wait_cap_s": 180,           # a lane back sooner than this is waited for in-process; later it is a PAUSE_LANE with a wake time
    "net_wait_cap_s": 600,       # one call waits this long for the network, then yields PAUSE_NETWORK
    "net_probe_up_stops": 3,     # network stops while the probe said up, inside net_probe_window_s: a proxy or DNS fault
    "net_probe_window_s": 300,
    "net_pause_s": 1800,         # that pause; doubles with each further such stop
    "net_pause_max_s": 21600,
    "max_polls": 3,              # busy / lock / duplicate polls before the call moves on
    "poll_s": 20,                # the wait of a poll when the stop names none
    "crash_rests": (30, 120),    # engine.CRASH_RESTS: delegate died; again after each rest, then it is a fault
    "bead_retries": 1,           # a bead-scope transient failure is tried once more
}


@dataclass(frozen=True)
class Stop:
    """The facts of one stopped call (the contract's `stop{}` plus `run.ref`). Built by delegate_link from the answer."""
    scope: str
    permanence: str
    retry_kind: str = "none"
    retry_at: float = 0.0       # epoch the lane is predicted back, or the suggested poll gap (0: none given)
    reason: str = ""            # wording only
    resumable: bool = False
    partial: bool = False       # work was seen before the stop
    ref: str = ""               # the vendor session of the call ("" when it never got one)
    lane: str = ""
    model: str = ""
    signal: int = 0             # the signal that ended the call (killed), 0 for none
    fix: str = ""
    fingerprint: str = ""


@dataclass(frozen=True)
class Ctx:
    """What the executor has counted for this step. now: the Clock's wall time."""
    now: float
    resumed: bool = False       # this call resumed a vendor thread
    attempt: int = 0
    polls: int = 0
    crashes: int = 0
    waited_lane_s: float = 0.0
    waited_net_s: float = 0.0
    net_up_stops: int = 0       # network stops in the last net_probe_window_s whose probe said up
    denied_retried: bool = False


@dataclass(frozen=True)
class Retry:
    not_before: float           # epoch; the executor sleeps until then
    resume: str = ""            # vendor ref to resume ("" = a new thread)
    charges: str = "attempt"    # the Ctx counter this action raises


@dataclass(frozen=True)
class Wait:
    until: float
    resume: str = ""
    charges: str = "waited_lane_s"


@dataclass(frozen=True)
class WaitNet:
    resume: str                 # the ref to resume once the probe passes ("" = a new thread)
    max_s: float                # most this call may still wait for the network
    charges: str = ""


@dataclass(frozen=True)
class NewThread:
    note: str = ""
    charges: str = "attempt"


@dataclass(frozen=True)
class Reroute:
    exclude: str                # lane or model the next pick must not use
    charges: str = "attempt"


@dataclass(frozen=True)
class Yield:
    """The run pauses with a wake; the bead stays open. retry_after: epoch hint (0: none). banner: say it once."""
    outcome: oc.RunOutcome
    retry_after: float = 0.0
    fix: str = ""
    banner: bool = False
    charges: str = ""


@dataclass(frozen=True)
class Fail:
    outcome: oc.RunOutcome
    charges: str = ""


def _say(stop):
    return ("%s %s" % (stop.reason, stop.fix)).strip() or "%s/%s/%s" % (stop.scope, stop.permanence, stop.retry_kind)


def _yield(kind, stop, retry_after=0.0, banner=False):
    return Yield(oc.make(kind, _say(stop)), retry_after, stop.fix, banner)


def _fail(kind, stop):
    return Fail(oc.make(kind, _say(stop)))


def _excluded(stop):
    return stop.lane if stop.scope == "lane" or not stop.model else stop.model


def _network(stop, ctx, cfg):
    """machine, transient, poll: the network (or a lock) is the machine's. Resume the same thread when the probe passes."""
    if ctx.net_up_stops >= cfg["net_probe_up_stops"]:  # the probe says up and the calls say down: visible, never silent
        over = ctx.net_up_stops - cfg["net_probe_up_stops"]
        return _yield(oc.Kind.PAUSE_NETWORK, stop, ctx.now + min(cfg["net_pause_s"] * (2 ** over), cfg["net_pause_max_s"]), True)
    left = cfg["net_wait_cap_s"] - ctx.waited_net_s
    if left <= 0:
        return _yield(oc.Kind.PAUSE_NETWORK, stop)
    return WaitNet(stop.ref if (ctx.resumed or stop.ref) else "", left)


def _machine_predicted(stop, ctx, cfg):
    return _yield(oc.Kind.PAUSE_LANE, stop, stop.retry_at)


def _machine_none(stop, ctx, cfg):
    """A crash of delegate itself: again as a fresh call after each rest, then a fault. Never an ask."""
    if stop.signal:
        return _yield(oc.Kind.PAUSE_KILLED, stop)
    rests = cfg["crash_rests"]
    if ctx.crashes < len(rests):
        return Retry(ctx.now + rests[ctx.crashes], "", "crashes")
    return _fail(oc.Kind.FAULT_CRASHED, stop)


def _machine_owner(stop, ctx, cfg):
    """setup, contract violations, no lane and no time: the machine's owner fixes it; the loop never asks per bead."""
    if stop.signal:
        return _yield(oc.Kind.PAUSE_KILLED, stop)
    return _yield(oc.Kind.PAUSE_LANE, stop)


def _caller(stop, ctx, cfg):
    return _fail(oc.Kind.FAULT_BAD_REQUEST, stop)


def _bead_owner(stop, ctx, cfg):
    """secrets: one fresh thread told to use apply_patch (2.14), then a fault. Never an ask."""
    if not ctx.denied_retried:
        return NewThread("apply_patch", "denied_retried")
    return _fail(oc.Kind.FAULT_DENIED, stop)


def _bead_none(stop, ctx, cfg):
    """worker_failed, schema_invalid, timeout: once more (resumed when the thread can be), then a fault."""
    if ctx.attempt < cfg["bead_retries"]:
        if stop.resumable and stop.ref:
            return Retry(ctx.now, stop.ref)
        return NewThread()
    return _fail(oc.Kind.FAULT_INFRA, stop)


def _poll_wait(stop, ctx, cfg):
    return ctx.now + (stop.retry_at if 0 < stop.retry_at <= cfg["wait_cap_s"] else cfg["poll_s"])


def _bead_poll(stop, ctx, cfg):
    """duplicate_task: a few polls, then the bead pauses."""
    if ctx.polls < cfg["max_polls"]:
        return Wait(_poll_wait(stop, ctx, cfg), stop.ref if stop.resumable else "", "polls")
    return _yield(oc.Kind.PAUSE_LANE, stop)


def _lane_owner(stop, ctx, cfg):
    """logged_out, credit_exhausted, model unsupported: the lane (or model) waits for its owner; the loop does not ask."""
    return _yield(oc.Kind.PAUSE_LANE, stop)


def _lane_predicted(stop, ctx, cfg):
    """rate_limited, held, hung: wait for it inside the cap, else pause with the time. A resumed thread moves at once."""
    if ctx.resumed:
        return NewThread("lane_out")
    gap = stop.retry_at - ctx.now
    if stop.retry_at and gap <= cfg["wait_cap_s"] - ctx.waited_lane_s:
        return Wait(stop.retry_at, "", "waited_lane_s")
    return _yield(oc.Kind.PAUSE_LANE, stop, stop.retry_at)


def _lane_poll(stop, ctx, cfg):
    """busy, vendor_blip: a few polls, then another lane (a resumed thread starts fresh there)."""
    if ctx.polls < cfg["max_polls"]:
        return Wait(_poll_wait(stop, ctx, cfg), stop.ref if (ctx.resumed and stop.resumable) else "", "polls")
    return NewThread("lane_out") if ctx.resumed else Reroute(_excluded(stop))


def _lane_none(stop, ctx, cfg):
    """A lane or model transient with no time: one other pick, then a pause."""
    if ctx.attempt < 2:
        return Reroute(_excluded(stop))
    return _yield(oc.Kind.PAUSE_LANE, stop)


# The table. Every legal tuple has a row; a new reason is a delegate classifier line, never a row here.
TABLE = {
    ("machine", "transient", "poll"): _network,
    ("machine", "transient", "predicted"): _machine_predicted,
    ("machine", "transient", "none"): _machine_none,
    ("machine", "needs_owner", "none"): _machine_owner,
    ("caller", "needs_owner", "none"): _caller,
    ("caller", "transient", "none"): _caller,       # no doc row: a caller's request does not heal by waiting
    ("caller", "transient", "predicted"): _caller,  # no doc row
    ("caller", "transient", "poll"): _caller,       # no doc row
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


def decide(stop, ctx, cfg=KNOBS):
    """The next Action for a stopped call. A signal on a machine stop is a kill (checkpoint kept, never a fail, never an
    ask). An unknown tuple pauses the lane: the contract may grow, the loop never fails or asks on what it cannot read."""
    if stop.signal and stop.scope == "machine":
        return _yield(oc.Kind.PAUSE_KILLED, stop)
    row = TABLE.get((stop.scope, stop.permanence, stop.retry_kind))
    if row is None:
        return _yield(oc.Kind.PAUSE_LANE, stop)
    return row(stop, ctx, cfg)
