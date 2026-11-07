"""The standalone step cursor and lifecycle over capabilities bound by the root."""
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from tlkernel import fence, wire
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint
from tlkernel.checks import CheckRun
from tlkernel.enums import Step
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.kinds import Kind
from tlkernel.locator import RunBundle, RunLocator
from tlkernel.parks import ParkStore
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.run import RunFinish, RunState
from tlkernel.wire import Open

from taskloop.adapters import beadtools
from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.pipeline.closing_record import RecordHost, RecordRun, RecordSteps
from taskloop.app.pipeline.crash import CrashHost, parked_crash
from taskloop.app.pipeline.cursor import select_step, stage_kind
from taskloop.app.pipeline.finish import stage_answer, terminal_state
from taskloop.app.pipeline.lifecycle import LeaseLike
from taskloop.app.pipeline.ports import BeadClosing, RoundSteps
from taskloop.domain import effects
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


@runtime_checkable
class Problem(Protocol):
    @property
    def text(self) -> str: ...


class Gate(Protocol):
    def green(self) -> bool: ...
    def run(self) -> object: ...


class Landing(Protocol):
    @property
    def gate(self) -> Gate: ...
    def finish(self, bead: Bead) -> str: ...


class OnceRun(Protocol):
    def go(self) -> int: ...
    def beat(self) -> None: ...
    def beat_died(self, err: BaseException) -> None: ...


class StageResult(Protocol):
    rc: int
    continued: bool
    reason: str
    terminal: RunState | None
    answer: RunFinish | None


class StageLifecycle(Protocol):
    def __call__(self, who: Identity, repo: str, mode: str, *, bundle: RunBundle,
                 events: bool, stores: Stores, log: RunLog) -> AbstractContextManager[StageResult]: ...


class Checkpoints(Protocol):
    def read(self) -> Checkpoint | None: ...
    def drop(self) -> None: ...
    def drop_unless_fenced(self) -> None: ...
    def save(self, *, step: str, stage: int) -> None: ...


class Resume(Protocol):
    def restore(self, ck: Checkpoint, *, late: bool) -> None: ...
    def point(self) -> tuple[PlanData | None, int, RoundState | None]: ...


class AskFlow(Protocol):
    def check(self) -> None: ...
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object: ...


class Briefs(Protocol):
    def export(self) -> None: ...


class Closer(Protocol):
    def pause(self, done: oc.RunOutcome) -> None: ...
    def apply(self, eff: effects.RaiseAsk, done: oc.RunOutcome, stats: str) -> None: ...


class Budget(Protocol):
    labels: list[str]


class Planner[T](Protocol):
    def plan(self, again: bool = False) -> T: ...
    def take(self, p: T) -> PlanData: ...


class Tree(Protocol):
    def reset(self, bead: Bead) -> object: ...


class Verifier(Protocol):
    def run(self, gaps: list[Open]) -> list[Open]: ...


class Review(Protocol):
    unchecked: list[Open]


class Steps(RecordSteps, Protocol):
    only: str | None


class Sessions(Protocol):
    def extend(self, values: Iterable[dict[str, object]], /) -> None: ...


class StandaloneHost[T](RecordHost, CrashHost, Protocol):
    prev_ck: str
    fenced: str
    bead_title: str
    bead_parent: str
    scope: str
    asked: bool
    landed_sha: str
    plan_data: PlanData | None
    last_run: CheckRun | None
    @property
    def sessions(self) -> Sessions: ...
    @property
    def who(self) -> Identity: ...
    @property
    def stores(self) -> Stores: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def fresh(self) -> bool: ...
    @property
    def moved(self) -> bool: ...
    @property
    def store(self) -> Beads: ...
    @property
    def budget(self) -> Budget: ...
    @property
    def ask_flow(self) -> AskFlow: ...
    @property
    def briefs(self) -> Briefs: ...
    @property
    def checkpoints(self) -> Checkpoints: ...
    @property
    def steps(self) -> Steps: ...
    @property
    def claim(self) -> fence.Claim | None: ...
    @property
    def dry(self) -> bool: ...
    @property
    def closer(self) -> Closer: ...
    @property
    def resume(self) -> Resume: ...
    @property
    def replan_first(self) -> bool: ...
    @property
    def lander(self) -> Landing: ...
    @property
    def tree(self) -> Tree: ...
    @property
    def planner(self) -> Planner[T]: ...
    @property
    def verifier(self) -> Verifier: ...
    @property
    def review(self) -> Review: ...


class Standalone[T]:
    def __init__(self, host: StandaloneHost[T], *, rounds: RoundSteps, once: Callable[[], OnceRun],
                 lease: Callable[[Callable[[], None], Callable[[BaseException], None]], LeaseLike],
                 closing: BeadClosing, has_land: Callable[[], bool], repo_of: Callable[[Git, str], str],
                 stage_run: StageLifecycle) -> None:
        self.host = host
        self.rounds, self.once, self.lease = rounds, once, lease
        self.closing, self.has_land, self.repo_of, self.stage_run = closing, has_land, repo_of, stage_run

    def run_stages(self, requested: str | None, *, continuous: bool) -> int:
        """Every caller enters the same lifecycle, including the loop's continuous sequence."""
        host = self.host
        locator = RunLocator(host.home)
        bundle = locator.get(host.run_id)
        assert bundle is not None
        mode = "loop" if continuous else f"stage:{requested}" if requested else "auto-next"
        with self.stage_run(host.who, bundle.repo, mode, bundle=bundle, events=False, stores=host.stores, log=host.log) as run:
            if continuous:
                run.rc = self.once().go()
                run.continued = host.moved
                settled = locator.get(host.run_id)
                if settled is not None and not settled.manifest.state.live:
                    run.terminal, run.reason = settled.manifest.state, settled.manifest.reason
            else:
                run.rc = self.one_stage(requested, locator)
                run.reason = host.why
                done = oc.make(host.kind, host.why, sha=host.landed_sha if host.kind is Kind.LANDED else "")
                run.terminal, run.answer = terminal_state(done), stage_answer(done, time.time())
            return run.rc

    def previous_run(self, locator: RunLocator) -> RunBundle | None:
        host = self.host
        previous = [b for b in locator.of_bead(host.bead, self.repo_of(host.git, host.wt)) if b.run != host.run_id]
        return previous[-1] if previous else None

    def next_step(self, locator: RunLocator, ck: Checkpoint | None, requested: str | None = None) -> Step:
        """The checkpoint is the cursor; the previous manifest also records life and completion."""
        host = self.host
        last = self.previous_run(locator)
        return select_step(last, ck, host.fresh, requested)

    def one_stage(self, requested: str | None, locator: RunLocator) -> int:
        host = self.host
        once = self.once()
        lease = self.lease(once.beat, once.beat_died)
        step = None
        try:
            ck = None if host.fresh else host.checkpoints.read()
            step = self.next_step(locator, ck, requested)
            locator.advance(host.run_id, step)  # failures retry the same step
            host.prev_ck = ck.run if ck else ""
            host.records.log_run()
            bead = beadtools.peek(host.store, host.bead)
            if bead is None:
                raise ValueError(f"bead {host.bead} not found")
            lease.start()
            host.bead_title, host.bead_parent, host.scope = bead.title, bead.parent, AcceptanceText.text(bead)
            host.budget.labels = list(bead.labels)
            host.ask_flow.check()
            host.briefs.export()
            if host.fresh:
                host.checkpoints.drop()
            step, ck = self.restore(ck, step, requested)
            self.refuse(step)
            locator.advance(host.run_id, step)
            host.steps.only = step
            following = self.dispatch(step, bead, ck)
            locator.advance(host.run_id, following)
            host.kind, host.why = stage_kind(step), ""
            return 0
        except fence.Fenced as err:
            host.fenced = err.why
            raise
        except Blocked as err:
            host.kind, host.why = err.kind, err.why
            if err.spec is not None:
                host.asked = host.ask_flow.raise_ask(err.spec, err.why, err.kind) is not None
            host.log.warn(host.why)
            return 1
        except ValueError as err:
            if step is not None and step in (Step.LAND, Step.CLOSE):
                parked_crash(host, step, err)
            else:
                host.kind, host.why = Kind.FAULT_ENGINE, str(err)
                host.log.warn(host.why)
            return 1
        except BaseException as err:
            if isinstance(err, Exception) and step is not None and step in (Step.LAND, Step.CLOSE):
                parked_crash(host, step, err)
                return 1
            host.kind, host.why = Kind.FAULT_ENGINE, str(err) or type(err).__name__
            raise
        finally:
            self.finish_stage(lease)

    def finish_stage(self, lease: LeaseLike) -> None:
        host = self.host
        lease.stop()
        host.steps.only = None
        host.steps.end()
        if host.fenced:
            return
        self.record_stage()
        if host.claim is not None and not fence.stale(host.store, host.claim):
            host.store.unclaim(host.bead)

    def record_stage(self) -> None:
        host = self.host
        done = oc.make(host.kind, host.why, sha=host.landed_sha)
        if done.kind is Kind.STAGE:  # the bead goes on: no park dropped, no pause, no close outcome kept for the next run
            pass
        elif done.finished and not host.dry:
            ParkStore(host.home).drop(host.bead)
        else:
            host.closer.pause(done)
            if done.kind is Kind.NOOP and not host.dry:
                host.closer.apply(effects.RaiseAsk(), done, "")
        host.records.finish(done, record=RecordRun(host).stage)

    def restore(self, ck: Checkpoint | None, step: Step, requested: str | None) -> tuple[Step, Checkpoint | None]:
        host = self.host
        if ck is None:
            return step, ck
        host.plan_data = ck.state.plan_data
        host.last_run = host.stores.check_run(ck.run, None).get()
        if host.last_run is not None:
            host.stores.check_run(host.run_id, None).write(host.last_run)
        if not host.plan_data or step in (Step.RESET, Step.GATE, Step.CLOSE, Step.REFLECT):
            host.resume.restore(ck, late=True)
            return step, ck
        plan, index, _ = host.resume.point()
        if plan is None and step not in (Step.PLAN, Step.REPLAN):
            if requested:
                raise ValueError(f"{step} refused: recorded work needs a new plan")
            step = Step.REPLAN if host.replan_first else Step.PLAN
        elif plan is not None and index != ck.stage:
            if requested:
                raise ValueError(f"{step} refused: recorded work must resume at plan stage {index + 1}")
            ck = ck.replace(stage=index, progress=None, n=0, rounds=0, feedback="")
            step = Step.WRITE if index < len(plan["stages"]) else Step.VERIFY
        return step, ck

    def refuse(self, step: Step) -> None:
        host = self.host
        if step is Step.LAND and not host.lander.gate.green():
            raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
        if step is Step.CLOSE and not self.has_land():
            raise ValueError("close refused: no land on record; run --stage land")

    def dispatch(self, step: Step, bead: Bead, ck: Checkpoint | None) -> Step | None:
        """Call one existing operation, then persist its next cursor without running it."""
        host = self.host
        if step in (Step.WRITE, Step.CHECKS, Step.REVIEW, Step.LOOK):
            return self.rounds.round_step(step, ck)
        if step in (Step.RESET, Step.PLAN, Step.REPLAN):
            return self.start_step(step, bead)
        following = self.finish_step(step, bead)
        if step not in (Step.CLOSE, Step.REFLECT):
            host.checkpoints.save(step=following or "", stage=ck.stage if ck else 0)
        return following

    def start_step(self, step: Step, bead: Bead) -> Step:
        host = self.host
        if step is Step.RESET:
            host.tree.reset(bead)
            following = Step.PLAN
        else:
            host.planner.take(host.planner.plan(again=step is Step.REPLAN))
            following = Step.WRITE
        host.checkpoints.save(step=following, stage=0)
        return following

    def finish_step(self, step: Step, bead: Bead) -> Step | None:
        host = self.host
        if step is Step.GATE:
            host.steps.begin(step, "standalone gate")
            result = host.lander.gate.run()
            if isinstance(result, Problem):
                raise ValueError(result.text)
            following = Step.LAND
        elif step is Step.LAND:
            try:
                sha = host.lander.finish(bead)
                if not sha:
                    raise ValueError("land refused: no land was recorded")
            except (Blocked, fence.Fenced):
                raise
            except Exception as err:
                done = parked_crash(host, step, err)
                raise Blocked(done.detail, kind=done.kind) from err
            host.landed_sha = sha
            following = Step.CLOSE
        elif step is Step.CLOSE:
            host.steps.begin(step, "close landed bead")
            if host.claim is None or self.closing.close(host.claim, "standalone close: land on record"):
                raise ValueError("close refused: bead close failed")
            host.checkpoints.drop_unless_fenced()
            return Step.REFLECT
        elif step is Step.REFLECT:
            host.steps.begin(step, "reflect")
            self.restore_sessions()
            host.reflection = host.reflector.reflect_run("done", "")
            return None
        else:  # verify
            host.steps.begin(step, "verify")
            if host.verifier.run(host.review.unchecked):
                raise ValueError("verify refused: unchecked items still need the owner")
            host.review.unchecked = []
            following = Step.GATE
        return following

    def restore_sessions(self) -> None:
        """A standalone reflection reads prior stage traces, stopping at the previous reflection."""
        host = self.host
        traces = [i.rec for i in host.stores.traces.read_from(0).items if i.rec.bead == host.bead and i.rec.worktree == host.wt]
        sessions = []
        for trace in reversed(traces):
            if trace.reflection is not None:
                break
            sessions[0:0] = [wire.dump(s) for s in trace.sessions]
        host.sessions.extend(sessions)
