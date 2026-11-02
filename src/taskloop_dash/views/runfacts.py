"""One engine run as typed facts: its steps with their phase and time, its calls with their fresh tokens, its Close, and what its
recorded state says of it. Built from the run's EngineLog records only (a Beat is no event): no process is probed, no text read.
Its liveness is the manifest's recorded state, which the reader sets.

Times that depend on the clock stay out: an open step ends at the run's last record, not at `now`, so a snapshot of an unchanged run
is byte-for-byte the same one (its version holds) until the run writes or its liveness flips."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts import log as rec
from taskloop.contracts.dash import Phase
from taskloop.contracts.runlife import Liveness
from taskloop.contracts.trace import Tokens
from taskloop.contracts.wire import Rec
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
    cost: float = 0.0
    cost_known: bool = False  # the cost the worker's answer gave is a fact (harness or free), not a missing number shown as 0


@dataclass(frozen=True)
class Wait:
    what: str
    secs: float


class StepBudget(Rec):
    """Only the totals stage cells display; one row per step, including zero overruns."""

    id: str
    checks: float = 0.0
    overruns: int = 0
    budget: float = 0.0
    elapsed: float = 0.0


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
    waits: tuple[Wait, ...] = ()  # the ended waits (a lane, the network, a resource, a lock ...)
    records: tuple[rec.EngineLog, ...] = ()  # drawer-only rows, never attached by the snapshot fold
    budgets: tuple[StepBudget, ...] = ()

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
                            (e.exec_seconds or 0.0) if e else 0.0))
    return tuple(out)


def calls_of(records: Sequence[rec.EngineLog]) -> tuple[Call, ...]:
    starts = {r.id: r for r in records if isinstance(r, rec.CallStart)}
    return tuple(Call(starts[r.id].t, starts[r.id].step, r.lane, fresh(r.tokens), r.cost, cost_known(r))
                 for r in records if isinstance(r, rec.CallEnd) and r.id in starts)


def cost_known(r: rec.CallEnd) -> bool:
    """Harness and free are facts; 'unknown' is not. A log from before the source was recorded counts a positive cost only."""
    return r.cost_source in ("harness", "free") or (not r.cost_source and r.cost > 0)


def waits_of(records: Sequence[rec.EngineLog]) -> tuple[Wait, ...]:
    starts = {r.id: r for r in records if isinstance(r, rec.WaitStart)}
    return tuple(Wait(starts[r.id].what.value, r.wait_seconds or 0.0) for r in records if isinstance(r, rec.WaitEnd) and r.id in starts)


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
    """Whole-log convenience wrapper; readers keep FoldState and append to it instead."""
    return run_from(name, fold(FoldState(), records), now)


class PendingCall(Rec):
    id: str
    t: float
    step: str


class FoldState(Rec):
    """Serializable facts, without the clock, liveness, or raw history.

    Tuples grow only with displayed facts (steps, calls, waits, transitions, artifacts, comments).
    Pairing frontiers keep only unfinished calls/waits; budgets hold four numbers per step.
    All other fields hold a single value or the latest record. Beats are deliberately absent.
    """

    start: rec.RunStart | None = None
    first_t: float | None = None
    last_t: float = 0.0
    spans: tuple[Span, ...] = ()
    calls: tuple[Call, ...] = ()
    waits: tuple[Wait, ...] = ()
    open_calls: tuple[PendingCall, ...] = ()
    open_waits: tuple[rec.WaitStart, ...] = ()
    transitions: tuple[rec.Transition, ...] = ()
    artifacts: tuple[rec.Artifacts, ...] = ()
    said: tuple[rec.Said, ...] = ()
    budgets: tuple[StepBudget, ...] = ()
    checks: rec.Checks | None = None
    close: rec.Close | None = None
    stuck: rec.Stuck | None = None
    assumed: int = 0
    lane: str = ""
    exit_code: int | None = None


def budget_append(b: StepBudget, r: rec.EngineLog) -> StepBudget:
    if isinstance(r, rec.Checks):
        return b.replace(checks=b.checks + sum(c.wall_min * 60 for c in r.run if c.wall_min))
    if isinstance(r, rec.Overrun):
        return b.replace(overruns=b.overruns + 1, budget=b.budget + r.budget_s, elapsed=b.elapsed + r.elapsed_s)
    return b


def latest(state: FoldState, r: rec.EngineLog) -> FoldState:
    """Single-value facts and the stuck episode; never keep unshown rows."""
    state = state.replace(first_t=r.t if state.first_t is None else state.first_t,
                          last_t=max(state.last_t, r.t) if state.first_t is not None else r.t,
                          stuck=stuck_of([state.stuck, r]) if state.stuck else stuck_of([r]))
    if isinstance(r, rec.RunStart) and state.start is None:
        return state.replace(start=r)
    if isinstance(r, rec.CallEnd):
        return state.replace(lane=r.lane or state.lane, exit_code=r.exit if r.exit is not None else state.exit_code)
    if isinstance(r, rec.Assumed):
        return state.replace(assumed=state.assumed + 1)
    if isinstance(r, rec.Close):
        return state.replace(close=r)
    if isinstance(r, rec.Checks):
        return state.replace(checks=r)
    return state


def step_append(spans: list[Span], budgets: list[StepBudget], steps: dict[str, int], r: rec.EngineLog) -> None:
    if isinstance(r, rec.StepStart):
        steps[r.id] = len(spans)
        spans.append(Span(r.id, r.step, phases.phase_of(r.step), r.t, None, "", r.text, 0.0))
        budgets.append(StepBudget(id=r.id))
    elif isinstance(r, rec.StepEnd) and r.id in steps:
        i = steps[r.id]
        s = spans[i]
        spans[i] = Span(s.id, s.step, s.phase, s.t0, r.t, r.outcome, s.text, r.exec_seconds or 0.0)
    if budgets:
        budgets[-1] = budget_append(budgets[-1], r)


def fold(state: FoldState, new_records: Sequence[rec.EngineLog]) -> FoldState:
    """Pure append fold. Pair ids are unique within an engine log; starts precede their ends."""
    spans, calls, waits = list(state.spans), list(state.calls), list(state.waits)
    budgets = list(state.budgets)
    steps = {s.id: i for i, s in enumerate(spans)}
    pending = {c.id: c for c in state.open_calls}
    opened = {w.id: w for w in state.open_waits}
    transitions, artifacts, said = list(state.transitions), list(state.artifacts), list(state.said)
    for r in new_records:
        if isinstance(r, rec.Beat):
            continue
        state = latest(state, r)
        step_append(spans, budgets, steps, r)
        if isinstance(r, rec.CallStart):
            pending[r.id] = PendingCall(id=r.id, t=r.t, step=r.step)
        elif isinstance(r, rec.CallEnd):
            start = pending.pop(r.id, None)
            if start:
                calls.append(Call(start.t, start.step, r.lane, fresh(r.tokens), r.cost, cost_known(r)))
        elif isinstance(r, rec.WaitStart):
            opened[r.id] = r
        elif isinstance(r, rec.WaitEnd):
            wait = opened.pop(r.id, None)
            if wait:
                waits.append(Wait(wait.what.value, r.wait_seconds or 0.0))
        elif isinstance(r, rec.Transition):
            transitions.append(r)
        elif isinstance(r, rec.Artifacts):
            artifacts.append(r)
        elif isinstance(r, rec.Said):
            said.append(r)
    return state.replace(spans=tuple(spans), calls=tuple(calls), waits=tuple(waits), budgets=tuple(budgets),
                         open_calls=tuple(pending.values()), open_waits=tuple(opened.values()),
                         transitions=tuple(transitions), artifacts=tuple(artifacts), said=tuple(said))


def run_from(name: str, state: FoldState, now: float) -> Run:
    """Project stored facts; liveness is replaced from the manifest by the reader."""
    s = state
    return Run(name, Liveness.LIVE, s.start, s.start.t if s.start else (s.first_t or 0.0), s.last_t,
               s.spans, s.calls, s.close, s.transitions, s.artifacts, s.checks,
               s.open_waits[-1] if s.open_waits else None, s.lane, s.exit_code,
               said=s.said, assumed=s.assumed, stuck=s.stuck, waits=s.waits, budgets=s.budgets)
