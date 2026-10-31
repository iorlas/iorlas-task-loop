"""The shared run entry: continuous loop runs or one recorded engine step."""
from __future__ import annotations

from typing import TYPE_CHECKING

from taskloop.adapters import beadtools
from taskloop.app.land.gate import Problem
from taskloop.app.run.layout import repo_of
from taskloop.app.run.records import terminal_state
from taskloop.app.run.run_once import RunOnce
from taskloop.app.run.stage_run import stage_run
from taskloop.app.slots.lease import Lease
from taskloop.app.track import verbs
from taskloop.app.wire.closeguard import guard_for, has_land
from taskloop.app.write.state import ACCEPT, REPLAN, StageState
from taskloop.contracts import fence, wire
from taskloop.contracts import log as rec
from taskloop.contracts.answers import WriteAnswerLook
from taskloop.contracts.bead import Bead
from taskloop.contracts.checkpoint import Checkpoint, StageProgress
from taskloop.contracts.enums import Step
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.plancheck import RoundState
from taskloop.contracts.run import RunState
from taskloop.domain import outcome as oc
from taskloop.domain.plan.matchers import AcceptanceText

if TYPE_CHECKING:
    from taskloop.app.run.engine import Engine


def parse_step(name: str) -> Step:
    try:
        return Step(name)
    except ValueError:
        raise ValueError(f"unknown stage {name!r}; choose from: {', '.join(Step)}") from None


def run_stages(e: Engine, requested: str | None, *, continuous: bool) -> int:
    """Every caller enters the same lifecycle, including the loop's continuous sequence."""
    locator = RunLocator(e.home)
    bundle = locator.get(e.run_id)
    assert bundle is not None
    mode = "loop" if continuous else f"stage:{requested}" if requested else "auto-next"
    with stage_run(e.who, bundle.repo, mode, bundle=bundle, events=False, stores=e.stores, log=e.log) as run:
        if continuous:
            run.rc = RunOnce(e).go()
            run.continued = e.moved
        else:
            run.rc = one_stage(e, requested, locator)
            run.reason = e.why
            run.terminal = terminal_state(oc.make(e.kind, e.why))
        return run.rc


def previous_run(e: Engine, locator: RunLocator) -> RunBundle | None:
    previous = [b for b in locator.of_bead(e.bead, repo_of(e.git, e.wt)) if b.run != e.run_id]
    last = previous[-1] if previous else None
    if last and last.manifest.state.live:
        raise ValueError(f"previous run {last.run} is still {last.manifest.state}")
    return last


def manifest_next(last: RunBundle | None, ck: Checkpoint | None) -> Step | None:
    if last is None:
        return None
    if ck is None or last.run == ck.run or last.started >= ck.t:
        return last.manifest.next_step
    return None


def next_step(e: Engine, locator: RunLocator, ck: Checkpoint | None, requested: str | None = None) -> Step:
    """The checkpoint is the cursor; the previous manifest also records life and completion."""
    last = previous_run(e, locator)
    if requested:
        return parse_step(requested)
    if e.fresh:
        return Step.RESET
    recorded = manifest_next(last, ck)
    if recorded is not None:
        return recorded
    if ck is not None:
        return checkpoint_next(ck)
    if last and last.manifest.state is RunState.DONE:
        raise ValueError("the last run is complete and has no next stage; name --stage or use --fresh")
    return Step.RESET


def checkpoint_next(ck: Checkpoint) -> Step:
    if ck.ended is not None:
        return Step.CLOSE
    if ck.step in ("gate-red", "land-verify-red"):
        return Step.REPLAN
    return parse_step(ck.step or "plan")


def one_stage(e: Engine, requested: str | None, locator: RunLocator) -> int:
    lease = Lease(e.store, e.bead, e.env.bead(EnvVar.TASK_LOOP_SLOT_BEAD), on_beat=RunOnce(e).beat)
    try:
        ck = None if e.fresh else e.checkpoints.read()
        step = next_step(e, locator, ck, requested)
        locator.advance(e.run_id, step)  # failures retry the same step
        e.prev_ck = ck.run if ck else ""
        e.records.log_run()
        bead = beadtools.peek(e.store, e.bead)
        if bead is None:
            raise ValueError(f"bead {e.bead} not found")
        lease.start()
        e.bead_title, e.bead_parent = bead.title, bead.parent
        e.budget.labels = list(bead.labels)
        e.scope = AcceptanceText.text(bead)
        e.ask_flow.check()
        e.briefs.export()
        if e.fresh:
            e.checkpoints.drop()
        step, ck = restore(e, ck, step, requested)
        refuse(e, step)
        locator.advance(e.run_id, step)
        e.steps.only = step
        following = dispatch(e, step, bead, ck)
        locator.advance(e.run_id, following)
        e.kind, e.why = Kind.LANDED if step is Step.LAND else Kind.DONE, ""
        return 0
    except e.Blocked as err:
        e.kind, e.why = err.kind, err.why
        if err.spec is not None:
            e.asked = e.ask_flow.raise_ask(err.spec, err.why, err.kind) is not None
        e.log.warn(e.why)
        return 1
    except ValueError as err:
        e.kind, e.why = Kind.FAULT_ENGINE, str(err)
        e.log.warn(e.why)
        return 1
    except BaseException as err:
        e.kind, e.why = Kind.FAULT_ENGINE, str(err) or type(err).__name__
        raise
    finally:
        lease.stop()
        e.steps.only = None
        e.steps.end()
        record_stage(e)
        if e.claim is not None and not fence.stale(e.store, e.claim):
            e.store.unclaim(e.bead)


def record_stage(e: Engine) -> None:
    outcome = oc.make(e.kind, e.why, sha=e.landed_sha).word
    e.log.emit(rec.Close(outcome=outcome, why=e.why, sha=e.landed_sha))
    e.records.file_trace(outcome, e.why, e.landed_sha)


def restore(e: Engine, ck: Checkpoint | None, step: Step, requested: str | None) -> tuple[Step, Checkpoint | None]:
    if ck is None:
        return step, ck
    e.plan_data = ck.state.plan_data
    e.last_run = e.stores.check_run(ck.run, None).get()
    if e.last_run is not None:
        e.stores.check_run(e.run_id, None).write(e.last_run)
    if not e.plan_data or step in (Step.RESET, Step.GATE, Step.CLOSE, Step.REFLECT):
        e.resume.restore(ck, late=True)
        return step, ck
    plan, index, _ = e.resume.point()
    if plan is None and step not in (Step.PLAN, Step.REPLAN):
        if requested:
            raise ValueError(f"{step} refused: recorded work needs a new plan")
        step = Step.REPLAN if e.replan_first else Step.PLAN
    elif plan is not None and index != ck.stage:
        if requested:
            raise ValueError(f"{step} refused: recorded work must resume at plan stage {index + 1}")
        ck = ck.replace(stage=index, progress=None, n=0, rounds=0, feedback="")
        step = Step.WRITE if index < len(plan["stages"]) else Step.VERIFY
    return step, ck


def refuse(e: Engine, step: Step) -> None:
    if step is Step.LAND and not e.lander.gate.green():
        raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
    if step is Step.CLOSE and not has_land(e.who, e.bead):
        raise ValueError("close refused: no land on record; run --stage land")


def dispatch(e: Engine, step: Step, bead: Bead, ck: Checkpoint | None) -> Step | None:
    """Call one existing operation, then persist its next cursor without running it."""
    if step in (Step.WRITE, Step.CHECKS, Step.REVIEW, Step.LOOK):
        return round_step(e, step, ck)
    if step in (Step.RESET, Step.PLAN, Step.REPLAN):
        return start_step(e, step, bead)
    following = finish_step(e, step, bead)
    if step not in (Step.CLOSE, Step.REFLECT):
        e.checkpoints.save(step=following or "", stage=ck.stage if ck else 0)
    return following


def start_step(e: Engine, step: Step, bead: Bead) -> Step:
    if step is Step.RESET:
        e.tree.reset(bead)
        following = Step.PLAN
    else:
        e.plan_data = e.planner.plan(again=step is Step.REPLAN)
        following = Step.WRITE
    e.checkpoints.save(step=following, stage=0)
    return following


def finish_step(e: Engine, step: Step, bead: Bead) -> Step | None:
    if step is Step.GATE:
        e.steps.begin(step, "standalone gate")
        result = e.lander.gate.run()
        if isinstance(result, Problem):
            raise ValueError(result.text)
        following = Step.LAND
    elif step is Step.LAND:
        sha = e.lander.finish(bead)
        if not sha:
            raise ValueError("land refused: no land was recorded")
        e.landed_sha = sha
        following = Step.CLOSE
    elif step is Step.CLOSE:
        e.steps.begin(step, "close landed bead")
        if e.claim is None or verbs.close_as(e.who, e.claim, "standalone close: land on record", e.store,
                                             guard_for(e.who, e.store, e.git, e.wt)):
            raise ValueError("close refused: bead close failed")
        e.checkpoints.drop_unless_fenced()
        return Step.REFLECT
    elif step is Step.REFLECT:
        e.steps.begin(step, "reflect")
        restore_sessions(e)
        e.reflection = e.reflector.reflect_run("done", "")
        return None
    else:  # verify
        e.steps.begin(step, "verify")
        if e.verifier.run(e.unchecked):
            raise ValueError("verify refused: unchecked items still need the owner")
        e.unchecked = []
        following = Step.GATE
    return following


def restore_sessions(e: Engine) -> None:
    """A standalone reflection reads prior stage traces, stopping at the previous reflection."""
    traces = [i.rec for i in e.stores.traces.read_from(0).items if i.rec.bead == e.bead and i.rec.worktree == e.wt]
    sessions = []
    for trace in reversed(traces):
        if trace.reflection is not None:
            break
        sessions[0:0] = [wire.dump(s) for s in trace.sessions]
    e.sessions.extend(sessions)


def round_step(e: Engine, step: Step, ck: Checkpoint | None) -> Step:
    s = round_state(e, step, ck)
    following, accepted = run_round_step(e, step, s)
    i = s.i
    if accepted:
        e.accepted.append(i)
        e.done.append(s.st["goal"])
        i += 1
        s.rounds, s.n, s.feedback = 0, 0, ""
        following = Step.VERIFY if s.last else Step.WRITE
    remember_round(e, s, following, i)
    return following


def round_state(e: Engine, step: Step, ck: Checkpoint | None) -> StageState:
    plan = e.plan_data
    i = ck.stage if ck else 0
    if plan is None or i >= len(plan["stages"]):
        raise ValueError(f"{step} refused: no active plan stage; run --stage plan")
    counters: RoundState | None = None
    if ck and (ck.n or ck.rounds or ck.feedback):
        counters = {"rounds": ck.rounds, "n": ck.n, "feedback": ck.feedback}
    s = e.stage_loop.begin(plan, i, counters)
    if ck and ck.progress:
        p = ck.progress
        s.red, s.red_now, s.failed_cmds = p.red, set(p.red_now), p.failed
        s.acc_only, s.acc_first, s.shots_fixed = p.acceptance_only, p.acceptance_first, p.shots_fixed
        s.w = wire.dump(p.write) if p.write else {}
        s.wfam = e.writer_family or ""
        s.wrote_unchecked = s.w.get("unchecked") or []
    if step is not Step.WRITE and not s.w:
        raise ValueError(f"{step} refused: no recorded writer answer; run --stage write")
    s.run = e.last_run
    return s


def run_round_step(e: Engine, step: Step, s: StageState) -> tuple[Step, bool]:
    if step is Step.WRITE:
        s.n += 1
        e.stats["writes"] += 1
        flow = e.stage_loop.writing.run(s, look=False)
        following = Step.REPLAN if flow == REPLAN else Step.WRITE if flow else Step.LOOK
    elif step is Step.LOOK:
        e.steps.begin(step, s.name)
        s.feedback = e.judge.look_step(s.st, s.w, s.name, s.last, checks=False)
        following = Step.WRITE if s.feedback else Step.CHECKS
    elif step is Step.CHECKS:
        flow = e.stage_loop.checking.run(s)
        following = Step.REPLAN if flow == REPLAN else Step.WRITE if flow else Step.REVIEW
    else:
        if s.run is None:
            raise ValueError("review refused: no recorded checks; run --stage checks")
        flow = e.stage_loop.reviewing.run(s)
        following = Step.REPLAN if flow == REPLAN else Step.WRITE
        return following, flow == ACCEPT
    return following, False


def remember_round(e: Engine, s: StageState, following: Step, i: int) -> None:
    answer = wire.load(WriteAnswerLook, dict(s.w, logic_only=s.w.get("logic_only", ""))) if s.w else None
    progress = None
    if i == s.i:
        progress = StageProgress(write=answer, red=s.red, red_now=sorted(s.red_now), failed=s.failed_cmds,
                                 acceptance_only=s.acc_only, acceptance_first=s.acc_first, shots_fixed=s.shots_fixed)
    e.checkpoints.save(step=following, stage=i, rounds=s.rounds, n=s.n, feedback=s.feedback, progress=progress)
    if s.run is not None:  # carry the check evidence forward across a separate look or review invocation
        e.stores.check_run(e.run_id, None).write(s.run)
