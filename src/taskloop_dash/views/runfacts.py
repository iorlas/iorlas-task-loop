"""One engine run as typed facts: its steps with their phase and time, its calls with their fresh tokens, its Close, and what the
runlife rule says of it. Built from the run's EngineLog records only (Beat included, for liveness): no process is probed, no text read.

Times that depend on the clock stay out: an open step ends at the run's last record, not at `now`, so a snapshot of an unchanged run
is byte-for-byte the same one (its version holds) until the run writes or its liveness flips."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts import log as rec
from taskloop.contracts.dash import Phase
from taskloop.contracts.runlife import Liveness, liveness
from taskloop.contracts.trace import Tokens
from taskloop_dash.views import phases


def fresh(t: Tokens) -> int:
    """Fresh tokens: input - cached + output."""
    return max(0, t.in_ - t.cached) + t.out


@dataclass(frozen=True)
class Span:
    """One step: `t1` is None while it is open (the run still writes)."""

    id: str
    step: str
    phase: Phase | None
    t0: float
    t1: float | None
    outcome: str
    text: str
    secs: float


@dataclass(frozen=True)
class Call:
    t: float
    step: str
    lane: str
    tokens: int
    role: str = ""
    secs: float = 0.0
    cost: float = 0.0
    cost_known: bool = False  # the cost the worker's answer gave is a fact (harness or free), not a missing number shown as 0


@dataclass(frozen=True)
class CheckTime:
    """One check result's time: the lane it ran in and the seconds it ran (cached and reused results ran no time)."""

    lane: str
    secs: float


@dataclass(frozen=True)
class Wait:
    what: str
    secs: float


@dataclass(frozen=True)
class Run:
    name: str
    life: Liveness
    start: rec.RunStart | None
    t0: float
    last_t: float
    spans: tuple[Span, ...]
    calls: tuple[Call, ...]
    close: rec.Close | None
    transitions: tuple[rec.Transition, ...]
    artifacts: tuple[rec.Artifacts, ...]
    checks: rec.Checks | None
    wait: rec.WaitStart | None
    lane: str
    exit_code: int | None  # the last call's worker exit code, when it gave one
    said: tuple[rec.Said, ...] = ()  # the engine's comments (and the owner's notes it passed on), oldest first
    assumed: int = 0  # Assumed records: what the planner planned around
    stuck: rec.Stuck | None = None  # the stuck episode still open at the run's newest record (stuck_of)
    check_times: tuple[CheckTime, ...] = ()  # every round's results, not only the newest
    waits: tuple[Wait, ...] = ()  # the ended waits (a lane, the network, a resource, a lock ...)

    @property
    def slot(self) -> str:
        s = self.start
        return (s.slot or Path(s.worktree.rstrip("/")).name) if s else ""

    def current(self) -> Span | None:
        """The step the run is in, or last was in."""
        return self.spans[-1] if self.spans else None

    def end_of(self, span: Span) -> float:
        return span.t1 if span.t1 is not None else self.last_t

    def tokens_in(self, span: Span) -> int:
        """Fresh tokens of the calls this step began (a call starts inside its step, under the step's name)."""
        return sum(c.tokens for c in self.calls if c.step == span.step and span.t0 <= c.t and (span.t1 is None or c.t < span.t1))


def spans_of(records: Sequence[rec.EngineLog]) -> tuple[Span, ...]:
    ends = {r.id: r for r in records if isinstance(r, rec.StepEnd)}
    out: list[Span] = []
    for r in records:
        if isinstance(r, rec.StepStart):
            e = ends.get(r.id)
            out.append(Span(r.id, r.step, phases.phase_of(r.step), r.t, e.t if e else None, e.outcome if e else "", r.text,
                            e.secs if e else 0.0))
    return tuple(out)


def calls_of(records: Sequence[rec.EngineLog]) -> tuple[Call, ...]:
    starts = {r.id: r for r in records if isinstance(r, rec.CallStart)}
    return tuple(Call(starts[r.id].t, starts[r.id].step, r.lane, fresh(r.tokens), starts[r.id].role, r.secs, r.cost, cost_known(r))
                 for r in records if isinstance(r, rec.CallEnd) and r.id in starts)


def cost_known(r: rec.CallEnd) -> bool:
    """Harness and free are facts; 'unknown' is not. A log from before the source was recorded counts a positive cost only."""
    return r.cost_source in ("harness", "free") or (not r.cost_source and r.cost > 0)


def check_times_of(records: Sequence[rec.EngineLog]) -> tuple[CheckTime, ...]:
    return tuple(CheckTime(c.lane, c.secs) for r in records if isinstance(r, rec.Checks) for c in r.run.results
                 if not (c.cached or c.reused or c.cancelled))


def waits_of(records: Sequence[rec.EngineLog]) -> tuple[Wait, ...]:
    starts = {r.id: r for r in records if isinstance(r, rec.WaitStart)}
    return tuple(Wait(starts[r.id].what.value, r.secs) for r in records if isinstance(r, rec.WaitEnd) and r.id in starts)


def open_wait(records: Sequence[rec.EngineLog]) -> rec.WaitStart | None:
    waits: dict[str, rec.WaitStart] = {}
    for r in records:
        if isinstance(r, rec.WaitStart):
            waits[r.id] = r
        elif isinstance(r, rec.WaitEnd):
            waits.pop(r.id, None)
    return list(waits.values())[-1] if waits else None


def stuck_of(records: Sequence[rec.EngineLog]) -> rec.Stuck | None:
    """The newest Stuck whose episode is still open: a silent one until any later record but a Beat or a Stuck, a same_red one until
    a later round that is green or red another way (domain/stuck.py writes them by the same rule)."""
    last: rec.Stuck | None = None
    for r in records:
        if isinstance(r, rec.Stuck):
            last = r
        elif last is None or isinstance(r, rec.Beat):
            continue
        elif last.why == "silent" or (isinstance(r, rec.Checks) and (not r.run.failed or r.run.signature() != last.sig)):
            last = None
    return last


def run_of(name: str, records: Sequence[rec.EngineLog], now: float) -> Run:
    body = [r for r in records if not isinstance(r, rec.Beat)]
    start = next((r for r in body if isinstance(r, rec.RunStart)), None)
    close = next((r for r in reversed(body) if isinstance(r, rec.Close)), None)
    last_t = max((r.t for r in body), default=0.0)
    lane = next((r.lane for r in reversed(body) if isinstance(r, rec.CallEnd) and r.lane), "")
    checks = next((r for r in reversed(body) if isinstance(r, rec.Checks)), None)
    code = next((r.exit for r in reversed(body) if isinstance(r, rec.CallEnd) and r.exit is not None), None)
    life = liveness(records, now)
    return Run(name, life, start, start.t if start else (body[0].t if body else 0.0), last_t, spans_of(body), calls_of(body), close,
               tuple(r for r in body if isinstance(r, rec.Transition)), tuple(r for r in body if isinstance(r, rec.Artifacts)),
               checks, open_wait(body) if life is Liveness.LIVE else None, lane, code,
               said=tuple(r for r in body if isinstance(r, rec.Said)), assumed=sum(1 for r in body if isinstance(r, rec.Assumed)),
               stuck=stuck_of(body), check_times=check_times_of(body), waits=waits_of(body))
