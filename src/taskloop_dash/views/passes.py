"""Passes and pieces of one bead, from its runs (oldest first).

A pass is one forward sweep through the phases: a step whose phase is not later than the pass's furthest one starts the next pass
(a fix round after a red check, a re-plan, a send-back), and so does every run. A pass ends by the Transition that left it, or, for a
run's last pass, by the run's Close. A piece is the bead's stretch on one slot (the Floor's bar): consecutive runs on one slot are
one piece, a run on another slot starts the next, and `from_slot`/`to_slot` link the comeback."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.dash import Cell, CellState, Msg, PassEnd, Phase, Piece, Resumed, Seg, SegKind
from taskloop.contracts.dash import Pass as PassRec
from taskloop.contracts.enums import Outcome
from taskloop.contracts.log import Said, Stuck
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views import phases
from taskloop_dash.views.runfacts import Run, Span

SMALL_SECS = 10 * 60  # a cell under this many seconds and SMALL_TOKENS is an empty tile (dash-spec §6)
SMALL_TOKENS = 100_000
SAID_ICON: Final = {"engine": "⚙️", "owner": "✉️"}  # who said it -> the message's icon (dash-spec 2.4: ✉️ is a note to the worker)
STUCK_ICON: Final = "🛑"
LAST_MAX = 160  # characters of a cell's last comment (the hover)


@dataclass(frozen=True)
class PassView:
    n: int
    run: Run
    spans: tuple[Span, ...]
    end: PassEnd
    text: str
    resumed: Resumed | None

    @property
    def t0(self) -> float:
        return self.spans[0].t0

    @property
    def t1(self) -> float:
        return self.run.end_of(self.spans[-1])

    @property
    def live(self) -> bool:
        """The run still writes and this is its last pass."""
        return self.run.life is Liveness.LIVE and self.end == "" and self.spans[-1].t1 is None


def groups_of(spans: Sequence[Span]) -> list[list[Span]]:
    """The spans of one run cut into passes: a phase no later than the pass's furthest, and not a repeat of the last, begins one."""
    groups: list[list[Span]] = [[spans[0]]]
    for s in spans[1:]:
        cur = groups[-1]
        far = max(phases.ORDER[x.phase] for x in cur if x.phase)
        if s.phase == cur[-1].phase or (s.phase and phases.ORDER[s.phase] > far):
            cur.append(s)
        else:
            groups.append([s])
    return groups


def loop_end(run: Run, last: Span, nxt: Span) -> PassEnd:
    """How the pass left: the typed cause of the Transition made between its last step and the next pass's first."""
    moved = [t for t in run.transitions if last.t0 <= t.t <= nxt.t0]
    end = phases.end_of_cause(moved[-1].cause) if moved else ""
    return end or ("replan" if nxt.phase == Phase.PLAN else "")


def resumed_of(run: Run, prev: Run | None) -> Resumed | None:
    """A run that comes back after an earlier one: where, and how long it waited for a slot (an owner's answer is not that wait)."""
    if prev is None or not run.start or not run.start.prev_run:
        return None
    if prev.close and phases.end_of_close(prev.close) == "asked":
        return None
    return Resumed(slot=run.slot, branch=run.start.branch, waited_secs=int(max(0.0, run.t0 - prev.last_t)))


def passes_of(runs: Sequence[Run]) -> list[PassView]:
    out: list[PassView] = []
    prev: Run | None = None
    for run in runs:
        spans = [s for s in run.spans if s.phase]
        if spans:
            groups = groups_of(spans)
            for i, g in enumerate(groups):
                if i + 1 < len(groups):
                    end = loop_end(run, g[-1], groups[i + 1][0])
                    text = phases.end_text(end)
                else:
                    end, text = last_end(run)
                out.append(PassView(len(out) + 1, run, tuple(g), end, text, resumed_of(run, prev) if i == 0 else None))
        prev = run
    return out


def last_end(run: Run) -> tuple[PassEnd, str]:
    """How a run's last pass ended: by its Close, or "stuck" when a stuck episode is open at its end (a live run, or a Close that
    names no end of its own, such as the ask after the same reds)."""
    end = phases.end_of_close(run.close) if run.close else ""
    if run.stuck is not None and end == "" and (run.close is not None or run.life is Liveness.LIVE):
        return "stuck", stuck_text(run.stuck)
    return end, phases.end_text(end, run.close.why if run.close else "")


def stuck_text(s: Stuck) -> str:
    where = f" in {s.step}" if s.step else ""
    if s.why == "silent":
        return f"stuck: silent past {int(s.limit_s // 60)}m{where}"
    return f"stuck: the same checks failed 3 times{where}"


def secs_of(run: Run, s: Span) -> float:
    return s.secs if s.t1 is not None and s.secs else run.end_of(s) - s.t0


def cells_of(p: PassView) -> list[Cell]:
    secs: dict[Phase, float] = {}
    tokens: dict[Phase, int] = {}
    for s in p.spans:
        if s.phase:
            secs[s.phase] = secs.get(s.phase, 0.0) + secs_of(p.run, s)
            tokens[s.phase] = tokens.get(s.phase, 0) + p.run.tokens_in(s)
    last = max((phases.ORDER[ph] for ph in secs), default=-1)
    out: list[Cell] = []
    for ph in Phase:
        if ph not in secs:
            out.append(Cell(phase=ph, state="skipped" if phases.ORDER[ph] < last else "empty"))
            continue
        here = phases.ORDER[ph] == last
        state: CellState = "small" if secs[ph] < SMALL_SECS and tokens[ph] < SMALL_TOKENS else "visited"
        if here and p.live:
            state = "live" if ph != Phase.LOOK else "you"
        elif here and p.end == "test_failed":
            state = "failed"
        elif here and p.end == "asked":
            state = "you"
        elif here and p.end == "stuck":
            state = "stuck"
        out.append(Cell(phase=ph, state=state, secs=int(secs[ph]), tokens=tokens[ph], last=last_said(p, ph)))
    return out


def said_in(p: PassView) -> list[tuple[Said, Phase | None]]:
    """The comments said during the pass's steps, oldest first, each with its step's phase; the run's last pass also takes those of
    the steps no phase draws after it began (reset, close: the Blocked and Reflect comments)."""
    ids = {s.id: s.phase for s in p.spans}
    drawn = {s.id for s in p.run.spans if s.phase}
    last = p.spans[-1].id == next((s.id for s in reversed(p.run.spans) if s.phase), "")
    return [(r, ids.get(r.step)) for r in p.run.said if r.step in ids or (last and r.step not in drawn and r.t >= p.t0)]


def last_said(p: PassView, ph: Phase) -> str:
    said = [r for r, at in said_in(p) if at == ph]
    lines = said[-1].text.strip().splitlines() if said else []
    return lines[0][:LAST_MAX] if lines else ""


def messages_of(p: PassView) -> list[Msg]:
    """This pass's comments and its stuck episode, newest first."""
    out = [Msg(t=r.t, icon=SAID_ICON.get(r.who, SAID_ICON["engine"]), who=r.who, md=r.text, phase=ph) for r, ph in said_in(p)]
    st = p.run.stuck
    if p.end == "stuck" and st is not None:
        out.append(Msg(t=st.t, icon=STUCK_ICON, who="loop", md=stuck_text(st), phase=phases.phase_of(st.step)))
    return [m for _, m in sorted(enumerate(out), key=lambda im: (-im[1].t, -im[0]))]  # newest first; of one second, the later said


def totals_of(ps: Sequence[PassView]) -> tuple[int, int]:
    """(seconds, fresh tokens) over the passes."""
    secs = sum(secs_of(p.run, s) for p in ps for s in p.spans)
    return int(secs), sum(p.run.tokens_in(s) for p in ps for s in p.spans)


def pass_rec(p: PassView) -> PassRec:
    return PassRec(n=p.n, cells=cells_of(p), end=p.end, end_text=p.text, resumed=p.resumed, messages=messages_of(p))


def landed(run: Run) -> bool:
    return bool(run.close and run.close.outcome in (Outcome.LANDED, Outcome.DONE))


def seg_kind(p: PassView, s: Span, failed: set[str]) -> SegKind:
    if s.t1 is None and p.run.life is Liveness.LIVE:
        return "look" if s.phase == Phase.LOOK else "live"
    return "failed" if s.id in failed else "stage"


def segs_of(run: Run, ps: Sequence[PassView], nxt: Run | None) -> list[Seg]:
    failed = {p.spans[-1].id for p in ps if p.end == "test_failed"}
    segs: list[Seg] = []
    for p in ps:
        for s in p.spans:
            seg = Seg(label=s.phase.value if s.phase else s.step, kind=seg_kind(p, s, failed), t0=s.t0, t1=max(s.t0, run.end_of(s)))
            prev = segs[-1] if segs else None
            if prev and prev.label == seg.label and prev.kind == seg.kind == "stage":
                segs[-1] = Seg(label=prev.label, kind=prev.kind, t0=prev.t0, t1=seg.t1)
            else:
                segs.append(seg)
    end = phases.end_of_close(run.close) if run.close else ""
    if run.close and end in ("asked", "parked", "lane_out"):
        until = nxt.t0 if nxt else run.close.t
        kind: SegKind = ("answered" if nxt else "ask") if end == "asked" else "parked"
        segs.append(Seg(label=phases.END_TEXT[end], kind=kind, t0=run.close.t, t1=max(run.close.t, until)))
    return segs


def pieces_of(project: str, bead: str, runs: Sequence[Run], passes: Sequence[PassView]) -> list[Piece]:
    """The bead's stretches on a slot, oldest first (n from 0)."""
    mine = [r for r in runs if any(p.run is r for p in passes)]
    stretches: list[tuple[str, list[Run]]] = []
    for r in mine:
        if stretches and stretches[-1][0] == r.slot:
            stretches[-1][1].append(r)
        else:
            stretches.append((r.slot, [r]))
    out: list[Piece] = []
    for i, (slot, rs) in enumerate(stretches):
        segs: list[Seg] = []
        for r in rs:
            nxt = mine[mine.index(r) + 1] if mine.index(r) + 1 < len(mine) else None
            segs += segs_of(r, [p for p in passes if p.run is r], nxt)
        out.append(Piece(bead=bead, project=project, slot=slot, n=i, segs=segs,
                         from_slot=stretches[i - 1][0] if i else None,
                         to_slot=stretches[i + 1][0] if i + 1 < len(stretches) else None, landed=landed(rs[-1])))
    return out
