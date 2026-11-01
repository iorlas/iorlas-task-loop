"""Pure stage logs from retained engine rows and the existing per-call live-event reader."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from taskloop.contracts import delegate, log
from taskloop.contracts.dash import Phase, StageAttempt, StageLog, StageRole, TermLine
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views import live_lines
from taskloop_dash.views.runfacts import Run, Span

if TYPE_CHECKING:
    from taskloop_dash.views.passes import PassView


def rows_of(run: Run, span: Span) -> list[log.EngineLog]:
    """Use record order so same-timestamp transitions belong to the step they left."""
    rows: list[log.EngineLog] = []
    active = False
    for r in run.records:
        if isinstance(r, log.StepStart):
            if active:
                break
            active = r.id == span.id
        if active:
            rows.append(r)
    return rows


def budget_of(p: PassView, phase: Phase) -> tuple[float | None, float]:
    rows = [r for s in p.spans if s.phase == phase for r in rows_of(p.run, s)]
    overruns = [r for r in rows if isinstance(r, log.Overrun)]
    if overruns:
        return sum(r.budget_s for r in overruns), sum(r.elapsed_s for r in overruns)
    limits = [c.wall_min * 60 for r in rows if isinstance(r, log.Checks) for c in r.run if c.wall_min]
    return (sum(limits) if limits else None), 0.0


def worker_attempt(start: log.CallStart, rows: Sequence[log.EngineLog], events: Sequence[delegate.LiveEvent], run: Run) -> StageAttempt:
    end = next((r for r in rows if isinstance(r, log.CallEnd) and r.id == start.id), None)
    info = next((r for r in events if isinstance(r, delegate.LiveStart)), None)
    lines = [ln for e in events if type(e) in live_lines.WORKER_LINES for ln in live_lines.WORKER_LINES[type(e)](e)]
    if end and end.reason:
        lines.append(TermLine(t=end.t, text=end.reason))
    return StageAttempt(id=start.id, t=start.t, secs=end.secs if end else max(0.0, run.last_t - start.t),
                        outcome=end.status if end else "running" if run.life is Liveness.LIVE else "interrupted",
                        lane=end.lane if end and end.lane else info.lane if info else "",
                        model=end.model if end and end.model else info.model if info else "",
                        live=end is None and run.life is Liveness.LIVE, lines=lines)


def step_roles(run: Run, span: Span, events: dict[int, Sequence[delegate.LiveEvent]]) -> list[tuple[str, StageAttempt]]:
    rows = rows_of(run, span)
    out = [(r.role, worker_attempt(r, rows, events.get(r.n, ()), run)) for r in rows if isinstance(r, log.CallStart)]
    for r in rows:
        if isinstance(r, log.Checks):
            for i, c in enumerate(r.run):
                lines = [TermLine(t=r.t, text=text) for text in [c.cmd, *c.tail.splitlines(), c.why] if text]
                out.append(("checks", StageAttempt(id=f"{span.id}:{r.run.round}:{i}", t=span.t0 + c.at, secs=c.secs,
                                                  outcome=c.word.value, lane=c.lane, lines=lines)))
    lines: list[TermLine] = []
    for r in rows:
        if isinstance(r, log.Transition) and r.from_id == span.id:
            lines.append(TermLine(t=r.t, text=f"{r.cause} → {r.to}" + (f": {r.detail}" if r.detail else "")))
        elif isinstance(r, log.Said):
            lines.append(TermLine(t=r.t, text=r.text))
        elif not isinstance(r, (log.CallStart, log.CallEnd)) and type(r) in live_lines.ENGINE_LINES:
            lines.extend(live_lines.ENGINE_LINES[type(r)](r))
    if lines:
        out.append(("engine", StageAttempt(id=span.id, t=span.t0, secs=max(0.0, run.end_of(span) - span.t0),
                                           outcome=span.outcome, lines=lines)))
    return out


def logs_of(p: PassView, events: dict[int, Sequence[delegate.LiveEvent]]) -> list[StageLog]:
    out: list[StageLog] = []
    for phase in Phase:
        roles: dict[str, list[StageAttempt]] = {}
        for span in p.spans:
            if span.phase == phase:
                for role, attempt in step_roles(p.run, span, events):
                    roles.setdefault(role, []).append(attempt)
        out.append(StageLog(phase=phase, roles=[StageRole(role=k, attempts=v) for k, v in roles.items()]))
    return out
