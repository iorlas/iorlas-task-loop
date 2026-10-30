"""One bead's drawer (GET /api/bead): the card, bd's text, every pass with its cells, the pictures, the live box and the open ask.

`Pass.messages` and `Cell.last` come from the engine's Said records, `Resumed.branch` from RunStart.branch, the stuck `LiveBox` from an
open Stuck episode. Left at its default: the live box's `subtasks` (no source)."""

from collections.abc import Sequence
from urllib.parse import quote

from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.dash import Artifact, AskCard, BeadDetail, CheckCount, LiveBox, Marker, Msg, Phase
from taskloop.contracts.delegate import LiveCmdEnd, LiveCmdStart, LiveEvent, LiveTokens
from taskloop.contracts.runlife import Liveness
from taskloop_dash.tails import parse_ts
from taskloop_dash.views import ledger, names, passes, phases
from taskloop_dash.views.askcards import ask_card, look_card, stale_of
from taskloop_dash.views.board import Board, blockers, is_work
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import ProjectIn

COMMENT_ICON = "💬"
EXITED_WHY = "the run stopped writing records"


def comment_msg(c: Comment) -> Msg:
    return Msg(t=parse_ts(c.created_at) or 0.0, icon=COMMENT_ICON, who=c.author, md=c.text)


def artifacts_of(bead: str, runs: Sequence[Run], ps: Sequence[passes.PassView]) -> list[Artifact]:
    """The files the runs left, newest first; each knows the pass and phase of the step that made it."""
    found: dict[str, Artifact] = {}
    for r in runs:
        for rec in r.artifacts:
            n = next((p.n for p in ps if p.run is r and any(s.id == rec.id for s in p.spans)), None)
            for name in rec.names:
                kind = "image" if names.kind_of(name) == "image" else "file"
                found[name] = Artifact(name=name, url=f"/api/artifact?bead={quote(bead)}&name={quote(name)}", kind=kind, t=rec.t,
                                       pass_n=n, phase=phases.phase_of(rec.step))
    return sorted(found.values(), key=lambda a: -a.t)


def live_box(run: Run, ps: Sequence[passes.PassView], events: Sequence[LiveEvent]) -> LiveBox | None:
    """The running worker: the stage and pass, the command, tokens of the current call, and the round of typed checks when it is
    testing. A run that died without a Close reads `exited`."""
    mine = [p for p in ps if p.run is run]
    cur = run.current()
    if run.life is Liveness.ENDED or not mine or cur is None or cur.phase is None:
        return None
    n = mine[-1].n
    if run.life is Liveness.CRASHED:
        return LiveBox(kind="exited", phase=cur.phase, pass_n=n, t=run.last_t, why=EXITED_WHY, exit_code=run.exit_code)
    if run.stuck is not None:
        st = run.stuck
        silent = int(max(0.0, run.last_t - st.since)) if st.why == "silent" else None
        return LiveBox(kind="stuck", phase=phases.phase_of(st.step) or cur.phase, pass_n=n, t=st.since, why=passes.stuck_text(st),
                       silent_secs=silent)
    cmds = [e for e in events if isinstance(e, LiveCmdStart)]
    done = {e.id for e in events if isinstance(e, LiveCmdEnd)}
    cmd = next((c.text for c in reversed(cmds) if c.id not in done), cmds[-1].text if cmds else "")
    toks = [e for e in events if isinstance(e, LiveTokens)]
    checks = None
    if cur.phase == Phase.TEST and run.checks:
        r = run.checks.run
        checks = CheckCount(passed=len(r.passed), failed=len(r.failed), unverified=len(r.unverified), total=len(r))
    tokens = max(0, toks[-1].in_ - toks[-1].cached) + toks[-1].out if toks else 0
    return LiveBox(kind="run", phase=cur.phase, pass_n=n, t=cur.t0, cmd=cmd, tokens=tokens, checks=checks)


def build(board: Board, p: ProjectIn, b: Bead, comments: Sequence[Comment], events: Sequence[LiveEvent]) -> BeadDetail:
    w = board.w
    runs = list(w.runs.get(b.id, ()))
    ps = board.passes_of(b.id)
    by_id = board.by_id[p.id]
    card = board.card(p, b, board.waits(p))
    ask: AskCard | None = None
    if w.asks.get(b.id) is not None and (card.column.value == "questions" or card.marker is Marker.SOFT_ASK):
        ask = ask_card(p.id, w.asks[b.id], ledger.similar_of(w.asks[b.id], p, w), stale_of(w.asks[b.id], p))
    else:
        ask = next((look_card(p.id, i, card.t or 0.0) for i in p.looks if i.bead == b.id), None)
    return BeadDetail(
        t=w.now, card=card, description=b.description, acceptance=b.acceptance_criteria, comments=[comment_msg(c) for c in comments],
        passes=[passes.pass_rec(x) for x in ps], artifacts=artifacts_of(b.id, runs, ps), waits_for=blockers(b, by_id),
        unblocks=[x.id for x in p.beads if is_work(x) and x.status != "closed" and b.id in blockers_ids(x)],
        live=live_box(runs[-1], ps, events) if runs else None, ask=ask)


def blockers_ids(b: Bead) -> set[str]:
    return {d.id for d in b.dependencies if d.type == "blocks"}
