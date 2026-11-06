"""One bead's drawer (GET /api/bead): the card, bd's text, every pass with its cells, the pictures, the live box and the open ask.

`Pass.messages` and `Cell.last` come from the engine's Said records, `Resumed.branch` from RunStart.branch, the stuck `LiveBox` from an
open Stuck episode. Left at its default: the live box's `subtasks` (no source)."""

from collections.abc import Sequence

from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.dash import Artifact, AskCard, BeadDetail, CheckCount, LiveBox, Marker, Msg, Phase
from taskloop.contracts.delegate import LiveCmdEnd, LiveCmdStart, LiveEvent, LiveTokens
from taskloop.contracts.log import Overrun, RetryDecision
from taskloop.contracts.runlife import Liveness
from taskloop_dash.tails import parse_ts
from taskloop_dash.views import ledger, passes, phases, stage_logs
from taskloop_dash.views.artifact_files import Item, url_of
from taskloop_dash.views.askcards import ask_card, look_card, stale_of
from taskloop_dash.views.board import Board, blockers, is_work
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import ProjectIn

COMMENT_ICON = "💬"
EXITED_WHY = "the run is lost: its process is gone and it recorded no end"


def comment_msg(c: Comment) -> Msg:
    return Msg(t=parse_ts(c.created_at) or 0.0, icon=COMMENT_ICON, who=c.author, md=c.text)


def decision_msgs(runs: Sequence[Run]) -> list[Msg]:
    """Why it was slow and why it switched: each Overrun (budget against elapsed) and RetryDecision (action and reason) the engine
    recorded, oldest first."""
    out: list[Msg] = []
    for r in runs:
        for x in r.records:
            if isinstance(x, Overrun):
                lane = f" on {x.lane}" if x.lane else ""
                out.append(Msg(t=x.t, icon="⏱", who="engine",
                               md=f"{x.stage}{lane} used its {x.budget_s:.0f} s budget ({x.elapsed_s:.0f} s) and was stopped"))
            elif isinstance(x, RetryDecision):
                lane = f" on {x.lane}" if x.lane else ""
                why = f": {x.reason}" if x.reason else ""
                out.append(Msg(t=x.t, icon="↪", who="engine", md=f"{x.step}{lane}: {x.action} (attempt {x.attempt}){why}"))
    return sorted(out, key=lambda m: m.t)


def artifacts_of(repo: str, bead: str, found: Sequence[Item], ps: Sequence[passes.PassView]) -> list[Artifact]:
    """The registered files, newest first (sidecar time); each knows the pass and phase of the stage attempt that made it: the n-th
    span of a step in a run is that step's attempt n."""
    where: dict[tuple[str, str, int], tuple[int, Phase | None]] = {}
    seen: dict[tuple[str, str], int] = {}
    for p in ps:
        for s in p.spans:
            k = (p.run.name, s.step)
            seen[k] = seen.get(k, 0) + 1
            where[(*k, seen[k])] = (p.n, s.phase)
    out: list[Artifact] = []
    for i in found:
        n, phase = where.get((i.run, i.stage, i.attempt), (None, None))
        out.append(Artifact(name=i.name, url=url_of(repo, bead, i), kind=i.kind, t=i.t, pass_n=n, phase=phase, role=i.role,
                            caption=i.caption, run=i.run, stage=i.stage, attempt=i.attempt))
    return out


def live_box(run: Run, ps: Sequence[passes.PassView], events: Sequence[LiveEvent]) -> LiveBox | None:
    """The running worker: the stage and pass, the command, tokens of the current call, and the round of typed checks when it is
    testing. A run that died without a Close reads `exited`."""
    mine = [p for p in ps if p.run is run]
    cur = run.current()
    if run.life is Liveness.ENDED or not mine or cur is None or cur.phase is None:
        return None
    n = mine[-1].n
    if run.life is Liveness.LOST:
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


def build(board: Board, p: ProjectIn, b: Bead, comments: Sequence[Comment], events: Sequence[LiveEvent],
          stage_events: dict[str, dict[int, Sequence[LiveEvent]]] | None = None, found: Sequence[Item] = ()) -> BeadDetail:
    w = board.w
    runs = list(w.runs.get((p.id, b.id), ()))
    ps = board.passes_of((p.id, b.id))
    by_id = board.by_id[p.id]
    card = board.card(p, b, board.waits(p))
    ask: AskCard | None = None
    a = w.asks.get((p.id, b.id))
    if a is not None and (card.column.value == "questions" or card.marker is Marker.SOFT_ASK):
        ask = ask_card(p.id, a, ledger.similar_of(a, p, w), stale_of(a, p))
    else:
        ask = next((look_card(p.id, i, card.t or 0.0) for i in p.looks if i.bead == b.id), None)
    return BeadDetail(
        t=w.now, card=card, description=b.description, acceptance=b.acceptance_criteria, comments=[comment_msg(c) for c in comments],
        decisions=decision_msgs(runs),
        passes=[passes.pass_rec(x).replace(logs=stage_logs.logs_of(x, (stage_events or {}).get(x.run.name, {}))) for x in ps],
        artifacts=artifacts_of(p.id, b.id, found, ps), waits_for=blockers(b, by_id),
        unblocks=[x.id for x in p.beads if is_work(x) and x.status != "closed" and b.id in blockers_ids(x)],
        live=live_box(runs[-1], ps, events) if runs else None, ask=ask)


def blockers_ids(b: Bead) -> set[str]:
    return {d.id for d in b.dependencies if d.type == "blocks"}
