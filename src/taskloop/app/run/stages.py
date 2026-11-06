"""The shared run entry: continuous loop runs or one recorded engine step."""
import time

from taskloop.adapters import beadtools
from taskloop.app.land.gate import Problem
from taskloop.app.run.closer_record import RecordRun
from taskloop.app.run.crash import parked_crash
from taskloop.app.run.finish import stage_answer, terminal_state
from taskloop.app.run.host import RunHost
from taskloop.app.run.layout import repo_of
from taskloop.app.run.run_once import RunOnce
from taskloop.app.run.stage_rounds import round_step
from taskloop.app.run.stage_run import stage_run
from taskloop.app.slots.lease import Lease
from taskloop.app.track import verbs
from taskloop.app.wire.closeguard import guard_for, has_land
from taskloop.contracts import fence, wire
from taskloop.contracts.bead import Bead
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.enums import Step
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.run import RunState
from taskloop.domain import effects
from taskloop.domain import outcome as oc
from taskloop.domain.plan.matchers import AcceptanceText


def parse_step(name: str) -> Step:
    try:
        return Step(name)
    except ValueError:
        raise ValueError(f"unknown stage {name!r}; choose from: {', '.join(Step)}") from None


def stage_kind(step: Step) -> Kind:
    """What one stage's run ends as: only a land is landed and only a close (or the reflect after it) is done."""
    if step is Step.LAND:
        return Kind.LANDED
    return Kind.DONE if step in (Step.CLOSE, Step.REFLECT) else Kind.STAGE


def run_stages(e: RunHost, requested: str | None, *, continuous: bool) -> int:
    """Every caller enters the same lifecycle, including the loop's continuous sequence."""
    locator = RunLocator(e.home)
    bundle = locator.get(e.run_id)
    assert bundle is not None
    mode = "loop" if continuous else f"stage:{requested}" if requested else "auto-next"
    with stage_run(e.who, bundle.repo, mode, bundle=bundle, events=False, stores=e.stores, log=e.log) as run:
        if continuous:
            run.rc = RunOnce(e).go()
            run.continued = e.moved
            settled = locator.get(e.run_id)
            if settled is not None and not settled.manifest.state.live:
                run.terminal, run.reason = settled.manifest.state, settled.manifest.reason
        else:
            run.rc = one_stage(e, requested, locator)
            run.reason = e.why
            done = oc.make(e.kind, e.why, sha=e.landed_sha if e.kind is Kind.LANDED else "")
            run.terminal, run.answer = terminal_state(done), stage_answer(done, time.time())
        return run.rc


def previous_run(e: RunHost, locator: RunLocator) -> RunBundle | None:
    previous = [b for b in locator.of_bead(e.bead, repo_of(e.git, e.wt)) if b.run != e.run_id]
    return previous[-1] if previous else None


def manifest_next(last: RunBundle | None, ck: Checkpoint | None) -> Step | None:
    if last is None:
        return None
    if ck is None or last.run == ck.run or last.started >= ck.t:
        return last.manifest.next_step
    return None


def next_step(e: RunHost, locator: RunLocator, ck: Checkpoint | None, requested: str | None = None) -> Step:
    """The checkpoint is the cursor; the previous manifest also records life and completion."""
    last = previous_run(e, locator)
    return select_step(last, ck, e.fresh, requested)


def select_step(last: RunBundle | None, ck: Checkpoint | None, fresh: bool, requested: str | None) -> Step:
    """Select the cursor without opening or changing a run."""
    if last and last.manifest.state.live:
        raise ValueError(f"previous run {last.run} is still {last.manifest.state}")
    if requested:
        return parse_step(requested)
    if fresh:
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


def one_stage(e: RunHost, requested: str | None, locator: RunLocator) -> int:
    once = RunOnce(e)
    lease = Lease(e.store, e.bead, e.env.bead(EnvVar.TASK_LOOP_SLOT_BEAD), on_beat=once.beat, on_death=once.beat_died)
    step = None
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
        e.kind, e.why = stage_kind(step), ""
        return 0
    except fence.Fenced as err:
        e.fenced = err.why
        raise
    except e.Blocked as err:
        e.kind, e.why = err.kind, err.why
        if err.spec is not None:
            e.asked = e.ask_flow.raise_ask(err.spec, err.why, err.kind) is not None
        e.log.warn(e.why)
        return 1
    except ValueError as err:
        if step is not None and step in (Step.LAND, Step.CLOSE):
            parked_crash(e, step, err)
        else:
            e.kind, e.why = Kind.FAULT_ENGINE, str(err)
            e.log.warn(e.why)
        return 1
    except BaseException as err:
        if isinstance(err, Exception) and step is not None and step in (Step.LAND, Step.CLOSE):
            parked_crash(e, step, err)
            return 1
        e.kind, e.why = Kind.FAULT_ENGINE, str(err) or type(err).__name__
        raise
    finally:
        finish_stage(e, lease)


def finish_stage(e: RunHost, lease: Lease) -> None:
    lease.stop()
    e.steps.only = None
    e.steps.end()
    if e.fenced:
        return
    record_stage(e)
    if e.claim is not None and not fence.stale(e.store, e.claim):
        e.store.unclaim(e.bead)


def record_stage(e: RunHost) -> None:
    done = oc.make(e.kind, e.why, sha=e.landed_sha)
    if done.kind is Kind.STAGE:  # the bead goes on: no park dropped, no pause, no close outcome kept for the next run
        pass
    elif done.finished and not e.dry:
        ParkStore(e.home).drop(e.bead)
    else:
        e.closer.pause(done)
        if done.kind is Kind.NOOP and not e.dry:
            e.closer.apply(effects.RaiseAsk(), done, "")
    e.records.finish(done, record=RecordRun(e).stage)


def restore(e: RunHost, ck: Checkpoint | None, step: Step, requested: str | None) -> tuple[Step, Checkpoint | None]:
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


def refuse(e: RunHost, step: Step) -> None:
    if step is Step.LAND and not e.lander.gate.green():
        raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
    if step is Step.CLOSE and not has_land(e.who, e.bead):
        raise ValueError("close refused: no land on record; run --stage land")


def dispatch(e: RunHost, step: Step, bead: Bead, ck: Checkpoint | None) -> Step | None:
    """Call one existing operation, then persist its next cursor without running it."""
    if step in (Step.WRITE, Step.CHECKS, Step.REVIEW, Step.LOOK):
        return round_step(e, step, ck)
    if step in (Step.RESET, Step.PLAN, Step.REPLAN):
        return start_step(e, step, bead)
    following = finish_step(e, step, bead)
    if step not in (Step.CLOSE, Step.REFLECT):
        e.checkpoints.save(step=following or "", stage=ck.stage if ck else 0)
    return following


def start_step(e: RunHost, step: Step, bead: Bead) -> Step:
    if step is Step.RESET:
        e.tree.reset(bead)
        following = Step.PLAN
    else:
        e.plan_data = e.planner.plan(again=step is Step.REPLAN)
        following = Step.WRITE
    e.checkpoints.save(step=following, stage=0)
    return following


def finish_step(e: RunHost, step: Step, bead: Bead) -> Step | None:
    if step is Step.GATE:
        e.steps.begin(step, "standalone gate")
        result = e.lander.gate.run()
        if isinstance(result, Problem):
            raise ValueError(result.text)
        following = Step.LAND
    elif step is Step.LAND:
        try:
            sha = e.lander.finish(bead)
            if not sha:
                raise ValueError("land refused: no land was recorded")
        except (e.Blocked, fence.Fenced):
            raise
        except Exception as err:
            done = parked_crash(e, step, err)
            raise e.Blocked(done.detail, kind=done.kind) from err
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


def restore_sessions(e: RunHost) -> None:
    """A standalone reflection reads prior stage traces, stopping at the previous reflection."""
    traces = [i.rec for i in e.stores.traces.read_from(0).items if i.rec.bead == e.bead and i.rec.worktree == e.wt]
    sessions = []
    for trace in reversed(traces):
        if trace.reflection is not None:
            break
        sessions[0:0] = [wire.dump(s) for s in trace.sessions]
    e.sessions.extend(sessions)
