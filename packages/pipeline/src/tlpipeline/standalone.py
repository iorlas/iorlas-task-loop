"""The standalone step cursor and lifecycle over capabilities bound by the root."""
import time
from collections.abc import Callable

from tlkernel import closeeffects as effects
from tlkernel import fence, wire
from tlkernel import runoutcome as oc
from tlkernel.acceptancetext import AcceptanceText
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.gitport import Git
from tlkernel.kinds import Kind
from tlkernel.locator import RunBundle, RunLocator
from tlkernel.parks import ParkStore
from tlpipeline.adapter_ports import PeekBead
from tlpipeline.blocked import Blocked
from tlpipeline.closing_record import RecordRun
from tlpipeline.crash import parked_crash
from tlpipeline.cursor import select_step, stage_kind
from tlpipeline.finish import stage_answer, terminal_state
from tlpipeline.lifecycle import LeaseLike
from tlpipeline.ports import BeadClosing, RoundSteps
from tlpipeline.standalone_roles import (
    Context,
    Cursor,
    Journalling,
    OnceRun,
    Operations,
    Problem,
    StageLifecycle,
    Values,
)


class Standalone[T]:
    def __init__(self, context: Context, cursor: Cursor, operations: Operations[T], values: Values, journalling: Journalling, *,
                 rounds: RoundSteps, once: Callable[[], OnceRun],
                 lease: Callable[[Callable[[], None], Callable[[BaseException], None]], LeaseLike],
                 closing: BeadClosing, has_land: Callable[[], bool], repo_of: Callable[[Git, str], str],
                 stage_run: StageLifecycle, peek_bead: PeekBead) -> None:
        self.context, self.cursor, self.operations = context, cursor, operations
        self.values, self.journalling = values, journalling
        self.peek_bead = peek_bead
        self.rounds, self.once, self.lease = rounds, once, lease
        self.closing, self.has_land, self.repo_of, self.stage_run = closing, has_land, repo_of, stage_run

    def run_stages(self, requested: str | None, *, continuous: bool) -> int:
        """Every caller enters the same lifecycle, including the loop's continuous sequence."""
        locator = RunLocator(self.journalling.home)
        bundle = locator.get(self.journalling.run_id)
        assert bundle is not None
        mode = "loop" if continuous else f"stage:{requested}" if requested else "auto-next"
        with self.stage_run(self.context.who, bundle.repo, mode, bundle=bundle,
                            events=False, stores=self.context.stores, log=self.journalling.log) as run:
            if continuous:
                run.rc = self.once().go()
                run.continued = self.context.moved
                settled = locator.get(self.journalling.run_id)
                if settled is not None and not settled.manifest.state.live:
                    run.terminal, run.reason = settled.manifest.state, settled.manifest.reason
            else:
                run.rc = self.one_stage(requested, locator)
                run.reason = self.journalling.why
                done = oc.make(self.journalling.kind, self.journalling.why,
                               sha=self.values.landed_sha if self.journalling.kind is Kind.LANDED else "")
                run.terminal, run.answer = terminal_state(done), stage_answer(done, time.time())
            return run.rc

    def previous_run(self, locator: RunLocator) -> RunBundle | None:
        previous = [b for b in locator.of_bead(self.journalling.bead, self.repo_of(self.context.git, self.context.wt))
                    if b.run != self.journalling.run_id]
        return previous[-1] if previous else None

    def next_step(self, locator: RunLocator, ck: Checkpoint | None, requested: str | None = None) -> Step:
        """The checkpoint is the cursor; the previous manifest also records life and completion."""
        last = self.previous_run(locator)
        return select_step(last, ck, self.context.fresh, requested)

    def one_stage(self, requested: str | None, locator: RunLocator) -> int:
        once = self.once()
        lease = self.lease(once.beat, once.beat_died)
        step = None
        try:
            ck = None if self.context.fresh else self.cursor.checkpoints.read()
            step = self.next_step(locator, ck, requested)
            locator.advance(self.journalling.run_id, step)  # failures retry the same step
            self.cursor.prev_ck = ck.run if ck else ""
            self.journalling.records.log_run()
            bead = self.peek_bead(self.context.store, self.journalling.bead)
            if bead is None:
                raise ValueError(f"bead {self.journalling.bead} not found")
            lease.start()
            self.values.bead_title, self.values.bead_parent, self.values.scope = bead.title, bead.parent, AcceptanceText.text(bead)
            self.operations.budget.labels = list(bead.labels)
            self.operations.ask_flow.check()
            self.operations.briefs.export()
            if self.context.fresh:
                self.cursor.checkpoints.drop()
            step, ck = self.restore(ck, step, requested)
            self.refuse(step)
            locator.advance(self.journalling.run_id, step)
            self.cursor.steps.only = step
            following = self.dispatch(step, bead, ck)
            locator.advance(self.journalling.run_id, following)
            self.journalling.kind, self.journalling.why = stage_kind(step), ""
            return 0
        except fence.Fenced as err:
            self.values.fenced = err.why
            raise
        except Blocked as err:
            self.journalling.kind, self.journalling.why = err.kind, err.why
            if err.spec is not None:
                self.values.asked = self.operations.ask_flow.raise_ask(err.spec, err.why, err.kind) is not None
            self.journalling.log.warn(self.journalling.why)
            return 1
        except ValueError as err:
            if step is not None and step in (Step.LAND, Step.CLOSE):
                parked_crash(self.journalling, step, err)
            else:
                self.journalling.kind, self.journalling.why = Kind.FAULT_ENGINE, str(err)
                self.journalling.log.warn(self.journalling.why)
            return 1
        except BaseException as err:
            if isinstance(err, Exception) and step is not None and step in (Step.LAND, Step.CLOSE):
                parked_crash(self.journalling, step, err)
                return 1
            self.journalling.kind, self.journalling.why = Kind.FAULT_ENGINE, str(err) or type(err).__name__
            raise
        finally:
            self.finish_stage(lease)

    def finish_stage(self, lease: LeaseLike) -> None:
        lease.stop()
        self.cursor.steps.only = None
        self.cursor.steps.end()
        if self.values.fenced:
            return
        self.record_stage()
        if self.context.claim is not None and not fence.stale(self.context.store, self.context.claim):
            self.context.store.unclaim(self.journalling.bead)

    def record_stage(self) -> None:
        done = oc.make(self.journalling.kind, self.journalling.why, sha=self.values.landed_sha)
        if done.kind is Kind.STAGE:  # the bead goes on: no park dropped, no pause, no close outcome kept for the next run
            pass
        elif done.finished and not self.context.dry:
            ParkStore(self.journalling.home).drop(self.journalling.bead)
        else:
            self.operations.closer.pause(done)
            if done.kind is Kind.NOOP and not self.context.dry:
                self.operations.closer.apply(effects.RaiseAsk(), done, "")
        self.journalling.records.finish(done, record=RecordRun(self.journalling).stage)

    def restore(self, ck: Checkpoint | None, step: Step, requested: str | None) -> tuple[Step, Checkpoint | None]:
        if ck is None:
            return step, ck
        self.cursor.state.plan_data = ck.state.plan_data
        self.cursor.last_run = self.context.stores.check_run(ck.run, None).get()
        if self.cursor.last_run is not None:
            self.context.stores.check_run(self.journalling.run_id, None).write(self.cursor.last_run)
        if not self.cursor.state.plan_data or step in (Step.RESET, Step.GATE, Step.CLOSE, Step.REFLECT):
            self.cursor.resume.restore(ck, late=True)
            return step, ck
        plan, index, _ = self.cursor.resume.point()
        if plan is None and step not in (Step.PLAN, Step.REPLAN):
            if requested:
                raise ValueError(f"{step} refused: recorded work needs a new plan")
            step = Step.REPLAN if self.cursor.replan_first else Step.PLAN
        elif plan is not None and index != ck.stage:
            if requested:
                raise ValueError(f"{step} refused: recorded work must resume at plan stage {index + 1}")
            ck = ck.replace(stage=index, progress=None, n=0, rounds=0, feedback="")
            step = Step.WRITE if index < len(plan["stages"]) else Step.VERIFY
        return step, ck

    def refuse(self, step: Step) -> None:
        if step is Step.LAND and not self.operations.lander.gate.green():
            raise ValueError("land refused: no green gate for the current tree and base; run --stage gate")
        if step is Step.CLOSE and not self.has_land():
            raise ValueError("close refused: no land on record; run --stage land")

    def dispatch(self, step: Step, bead: Bead, ck: Checkpoint | None) -> Step | None:
        """Call one existing operation, then persist its next cursor without running it."""
        if step in (Step.WRITE, Step.CHECKS, Step.REVIEW, Step.LOOK):
            return self.rounds.round_step(step, ck)
        if step in (Step.RESET, Step.PLAN, Step.REPLAN):
            return self.start_step(step, bead)
        following = self.finish_step(step, bead)
        if step not in (Step.CLOSE, Step.REFLECT):
            self.cursor.checkpoints.save(step=following or "", stage=ck.stage if ck else 0)
        return following

    def start_step(self, step: Step, bead: Bead) -> Step:
        if step is Step.RESET:
            self.operations.tree.reset(bead)
            following = Step.PLAN
        else:
            self.operations.planner.take(self.operations.planner.plan(again=step is Step.REPLAN))
            following = Step.WRITE
        self.cursor.checkpoints.save(step=following, stage=0)
        return following

    def finish_step(self, step: Step, bead: Bead) -> Step | None:
        if step is Step.GATE:
            self.cursor.steps.begin(step, "standalone gate")
            result = self.operations.lander.gate.run()
            if isinstance(result, Problem):
                raise ValueError(result.text)
            following = Step.LAND
        elif step is Step.LAND:
            try:
                sha = self.operations.lander.finish(bead)
                if not sha:
                    raise ValueError("land refused: no land was recorded")
            except (Blocked, fence.Fenced):
                raise
            except Exception as err:
                done = parked_crash(self.journalling, step, err)
                raise Blocked(done.detail, kind=done.kind) from err
            self.values.landed_sha = sha
            following = Step.CLOSE
        elif step is Step.CLOSE:
            self.cursor.steps.begin(step, "close landed bead")
            if self.context.claim is None or self.closing.close(self.context.claim, "standalone close: land on record"):
                raise ValueError("close refused: bead close failed")
            self.cursor.checkpoints.drop_unless_fenced()
            return Step.REFLECT
        elif step is Step.REFLECT:
            self.cursor.steps.begin(step, "reflect")
            self.restore_sessions()
            self.journalling.reflection = self.journalling.reflector.reflect_run("done", "")
            return None
        else:  # verify
            self.cursor.steps.begin(step, "verify")
            if self.operations.verifier.run(self.operations.review.unchecked):
                raise ValueError("verify refused: unchecked items still need the owner")
            self.operations.review.unchecked = []
            following = Step.GATE
        return following

    def restore_sessions(self) -> None:
        """A standalone reflection reads prior stage traces, stopping at the previous reflection."""
        traces = [i.rec for i in self.context.stores.traces.read_from(0).items
                  if i.rec.bead == self.journalling.bead and i.rec.worktree == self.context.wt]
        sessions = []
        for trace in reversed(traces):
            if trace.reflection is not None:
                break
            sessions[0:0] = [wire.dump(s) for s in trace.sessions]
        self.values.sessions.extend(sessions)
