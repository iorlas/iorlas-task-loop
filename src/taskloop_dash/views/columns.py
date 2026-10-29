"""The Board's column, the one marker, the status line and the stage dots of a bead: pure functions of typed facts (dash-spec §2.4, §3).

`Facts` holds what the engine and bd said, already typed: the newest run's liveness and current step, its Close, an open ask, an open
look, bd's status and dependencies. Nothing here reads a log, a process or a sentence for a fact; the strings it carries are shown,
never decided on. A live run with an open stuck episode (the engine's Stuck record) reads STUCK. A soft ask marks the bead but
moves no column: the bead goes on."""

from dataclasses import dataclass
from typing import Final

from taskloop.contracts.dash import Column, DotState, Marker, Phase, PhaseDot, Tone
from taskloop.contracts.enums import Outcome
from taskloop.contracts.log import Close, WaitStart
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views import names, phases

PARKING = (Outcome.PARKED, Outcome.BLOCKED)
CURRENT_DOT: Final[dict[Marker, DotState]] = {
    Marker.RUN: "live", Marker.ASK: "you", Marker.LOOK: "you", Marker.EXITED: "bad", Marker.STUCK: "bad"}


@dataclass(frozen=True)
class Facts:
    closed: bool = False  # bd says closed
    claimed: bool = False  # bd says in progress
    ask: bool = False  # AskStore holds an open or parked blocking ask of the bead
    soft_ask: bool = False  # ... a soft one: the run went on with its default and the question stays open
    look: bool = False  # an open item of an owner-look bead names the bead
    life: Liveness | None = None  # the newest run's runlife state; None: the bead has no run
    phase: Phase | None = None  # the phase of that run's current (else last) step
    close: Close | None = None  # that run's Close
    blocked: bool = False  # an open `blocks` dependency
    stuck: bool = False  # that run is live and a stuck episode of it is open
    # shown, never decided on:
    stuck_line: str = ""
    ask_line: str = ""
    step_text: str = ""
    wait: WaitStart | None = None
    blocker: str = ""
    closed_reason: str = ""
    assignee: str = ""

    @property
    def open_run(self) -> bool:
        return self.life in (Liveness.LIVE, Liveness.CRASHED)


def column(f: Facts) -> Column:
    if f.ask:
        return Column.QUESTIONS
    if f.look:
        return Column.LOOK
    if f.closed:
        return Column.DONE
    if f.open_run:
        return phases.PHASE_COLUMN.get(f.phase, Column.WORKING) if f.phase else Column.WORKING
    return Column.WORKING if f.claimed else Column.BACKLOG


def marker(f: Facts) -> Marker:
    parked = f.close is not None and f.close.outcome in PARKING
    rules = ((f.ask, Marker.ASK), (f.look, Marker.LOOK), (f.closed, Marker.DONE), (f.life is Liveness.LIVE and f.stuck, Marker.STUCK),
             (f.soft_ask, Marker.SOFT_ASK), (f.life is Liveness.LIVE, Marker.RUN), (f.life is Liveness.CRASHED, Marker.EXITED),
             (f.claimed, Marker.RUN), (parked, Marker.PARKED), (f.blocked, Marker.BLOCKED))
    return next((m for ok, m in rules if ok), Marker.READY)


def first_line(text: str, limit: int = 160) -> str:
    lines = text.strip().splitlines()
    return lines[0][:limit] if lines else ""


def wait_line(w: WaitStart) -> str:
    until = f" until {names.hhmm(w.until)}" if w.until else ""
    return f"waiting for {w.what.value.replace('_', ' ')}{until}"


def status_line(f: Facts) -> str:
    """One line: why the bead is where it is, from the typed facts and the engine's own one-liners."""
    running = wait_line(f.wait) if f.wait else first_line(f.step_text) or (f.phase.value if f.phase else "running")
    parked = f.close is not None and f.close.outcome in PARKING
    why = first_line(f.close.why) or phases.END_TEXT[phases.end_of_close(f.close)] or "parked" if f.close else ""
    rules = ((f.ask, first_line(f.ask_line) or "waiting for your answer"), (f.look, "waiting for your look"),
             (f.closed, first_line(f.closed_reason) or "closed"), (f.life is Liveness.LIVE and f.stuck, f.stuck_line or "stuck"),
             (f.soft_ask, first_line(f.ask_line) or "a question waits, the run went on"), (f.life is Liveness.LIVE, running),
             (f.life is Liveness.CRASHED, "the run stopped writing records"),
             (f.claimed, f"claimed by {f.assignee}" if f.assignee else "claimed"), (parked, why),
             (f.blocked and bool(f.blocker), f"waits for {f.blocker}"))
    return next((text for ok, text in rules if ok), "ready")


def tone_of(m: Marker) -> Tone:
    if m in (Marker.ASK, Marker.LOOK, Marker.SOFT_ASK):
        return "you"
    if m in (Marker.STUCK, Marker.EXITED):
        return "bad"
    return "run" if m is Marker.RUN else ""


def dots_of(visited: set[Phase], current: Phase | None, m: Marker, closed: bool) -> list[PhaseDot]:
    """One dot per phase: done when visited (all, when closed), the current one live, waiting on you, or bad."""
    if not visited and not closed and current is None:
        return []
    out: list[PhaseDot] = []
    for ph in Phase:
        state: DotState = "done" if closed or ph in visited else "todo"
        if not closed and ph == current:
            state = CURRENT_DOT.get(m, state)
        out.append(PhaseDot(phase=ph, state=state))
    return out
