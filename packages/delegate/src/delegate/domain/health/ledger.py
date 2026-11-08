"""HealthLedger: lane health as a replayable fold over history rows (delegate-rdt, delegate-a9x).

Pure: no clock, no I/O. `fold(rows, state)` turns finished-run rows into an `any_breaker.State`;
`view(state, lane, model, t)` answers "may this
(lane, model) pair launch at time t, and if not why". The same rows replayed in time order give the same answer, so a past incident is a
regression fixture (tests/domain/test_health.py, golden/health_replay.json).

Two kinds of fact, both read from the run's outcome:
  lane facts   rate_limited, credit_exhausted, logged_out: the whole lane is out until a time (the vendor's, else a probe time).
  pair facts   vendor_blip, worker_failed, hung: counted per fingerprint per (lane, model) inside a window; enough of them bench the pair on
               a 15/30/60 min ladder. A launch after a bench ends is the canary: it passes (a `done`) and the ladder resets, or it fails and
               the next rung starts at once.
Never counted: bad_request (the caller's fault), network, killed, timeout, secrets, schema_invalid, refusals.
"""

from dataclasses import dataclass
from types import MappingProxyType

from any_breaker import OK, OPEN, OUT, RELEASE, Breaker, Fact, Out, Policy, Rule, State

from delegate.contracts.history import CanaryRow, Failure, HistoryRow, ReleaseRow, RunRow
from delegate.contracts.json_types import Json
from delegate.contracts.routing import BreakerPolicy
from delegate.domain.health.matchers import fingerprint

LANE_KINDS = ("rate_limited", "credit_exhausted", "logged_out")
BREAKER = MappingProxyType({"vendor_blip": {"tasks": 2}, "worker_failed": {"tasks": 3}, "hung": {"n": 2, "window_min": 30, "tasks": 1}})
STATES = ("up", "busy", "exhausted", "logged_out", "held", "broken")


def failure_fields(outcome: str | None, source: str, say: str | None, until: float | None = None) -> dict[str, Json]:
    """-> the health fields a run or refusal row carries; {} for a done run (outcome None)."""
    if not outcome:
        return {}
    return {"outcome": outcome, "fingerprint": fingerprint(outcome, source, say), "say": (say or "")[:240], "until": until}


@dataclass(frozen=True)
class PairView:
    """One (lane, model) pair at one time. `usable` is False while a bench or a lane-level out is running; once it ends the pair is `up`
    with canary True: the next launch is the one probe before full traffic."""

    state: str = "up"
    usable: bool = True
    canary: bool = False
    until: float | None = None
    source: str | None = None
    kind: str | None = None
    evidence: str = ""
    rung: int = 0
    last_failures: tuple[Failure, ...] = ()

    def as_dict(self) -> dict[str, Json]:
        return {
            "state": self.state,
            "usable": self.usable,
            "canary": self.canary,
            "until": self.until,
            "source": self.source,
            "kind": self.kind,
            "evidence": self.evidence,
            "rung": self.rung,
            "last_failures": [{"ts": f.ts, "outcome": f.outcome, "say": f.say} for f in self.last_failures],
        }


def fact_of(row: HistoryRow) -> list[Fact]:
    """The facts a history row is: the lane is a key of its own and `lane|model` another; a run that worked proves both. [] when the row
    is not a fact: a refusal, a gap, a reap, a caller fault, network, killed, timeout..."""
    if isinstance(row, ReleaseRow):  # `route.py report --event ok`: the owner says the lane is fine
        return [Fact(RELEASE, row.ts, row.lane), Fact(RELEASE, row.ts, row.lane + "|", prefix=True)]
    if isinstance(row, CanaryRow) or (isinstance(row, RunRow) and row.done):
        return [Fact(OK, row.ts, row.lane), Fact(OK, row.ts, f"{row.lane}|{row.model}")]
    if not isinstance(row, RunRow):
        return []
    o, say = row.outcome, row.say or ""
    if o in LANE_KINDS:  # a spending limit and a logout have no vendor timer: the probe time rules
        return [Fact(o, row.ts, row.lane, until=row.until if o == "rate_limited" else None, note=say)]
    if o in BREAKER:
        fp = row.fingerprint or fingerprint(o, "", say)
        return [Fact(o, row.ts, f"{row.lane}|{row.model}", fp=fp, source=row.task or row.run_id, note=say)]
    return []


def policy_of(pol: BreakerPolicy) -> Policy:
    return Policy(
        n=pol.n,
        window_s=pol.window_min * 60,
        ladder_s=tuple(m * 60 for m in pol.ladder_min),
        rules={
            k: Rule(n=r.get("n"), window_s=r["window_min"] * 60 if "window_min" in r else None, distinct=r["tasks"])
            for k, r in BREAKER.items()
        },
        outs={
            "rate_limited": Out(pol.guess_s),
            "credit_exhausted": Out(pol.credit_probe_s, "probe"),
            "logged_out": Out(pol.logout_s, "probe"),
        },
    )


class HealthLedger:
    """The fold, with the breaker policy it runs under: a thin consumer of any_breaker."""

    def __init__(self, policy: BreakerPolicy) -> None:
        self.pol = policy
        self.breaker = Breaker(policy_of(policy))

    def step(self, state: State, row: HistoryRow) -> None:
        """Apply one history row to `state` (mutates). Rows must come in time order."""
        for f in fact_of(row):
            self.breaker.step(state, f)

    def fold(self, rows: list[HistoryRow], state: State | None = None) -> State:
        """The state after `rows` on top of `state` (a checkpoint, else empty): fold(all) == fold(tail, fold(head))."""
        return self.breaker.fold((f for r in rows for f in fact_of(r)), state)

    def view(self, state: State, lane: str, model: str, t: float) -> PairView:
        lv, pv = self.breaker.view(state, lane, t), self.breaker.view(state, f"{lane}|{model}", t)
        last = tuple(Failure(ts=f.ts, outcome=f.kind, say=f.note) for f in pv.recent)
        if lv.state == OUT:
            state_word = "logged_out" if lv.kind == "logged_out" else "exhausted"
            return PairView(state_word, False, False, lv.until, lv.source, lv.kind, lv.evidence, pv.rung, last)
        if pv.state == OPEN:
            return PairView("broken", False, lv.canary, pv.until, pv.source, pv.kind, pv.evidence, pv.rung, last)
        src = pv if pv.canary else lv
        return PairView(canary=lv.canary or pv.canary, kind=src.kind, evidence=src.evidence, rung=pv.rung, last_failures=last)


def combine(v: PairView, held: bool = False, busy: bool = False) -> str:
    """-> the one state word of a pair: held > logged_out > exhausted > broken > busy > up. Holds and leases are not history facts."""
    if held:
        return "held"
    if v.state in ("logged_out", "exhausted", "broken"):
        return v.state
    return "busy" if busy else "up"


def stale_usage(read_at: float | None, t: float, policy: BreakerPolicy) -> float | None:
    """-> hours old when a usage reading is older than the stale limit (it is then unknown, never a silent gate), else None."""
    return round((t - read_at) / 3600, 1) if read_at and t - read_at > policy.stale_usage_s else None
