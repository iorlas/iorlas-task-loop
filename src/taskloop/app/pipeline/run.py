"""The run body over local stage capabilities and shared run state."""
from collections.abc import Callable, Sequence
from typing import Protocol

from tlkernel import fence
from tlkernel.askenums import AskClass
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import RunState
from tlkernel.config import EngineConfig
from tlkernel.delegateport import Refusal
from tlkernel.enums import Step
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.wire import Open

from taskloop.adapters import beadtools, ident
from taskloop.adapters.looks import Methods
from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.pipeline.crash import CrashHost, parked_crash
from taskloop.app.pipeline.lifecycle import Ended, LeaseLike
from taskloop.app.pipeline.ports import HeadHistory
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.lanes import pin
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.domain.review.kinds import UNCHECKED_KINDS


class PlannerCap(Protocol):
    def grant(self) -> None: ...
    def answered_words(self) -> str: ...
    def blocked(self, detail: str = "") -> Exception: ...


class Planner[T](Protocol):
    @property
    def cap(self) -> PlannerCap: ...
    def plan(self, again: bool = False) -> T: ...
    def take(self, p: T) -> PlanData: ...


class Verifier(Protocol):
    def run(self, gaps: list[Open]) -> list[Open]: ...


class Outbound(Protocol):
    def wip_push(self, i: int) -> None: ...


class Lander(Protocol):
    @property
    def out(self) -> Outbound: ...
    def finish(self, bead: Bead) -> str: ...


class Rebase(Protocol):
    def onto_base(self, salvage: bool = False, between: bool = False) -> str: ...


class Salvage(Protocol):
    def salvage(self) -> str: ...


class Restart(Protocol):
    def again(self, why: str) -> bool: ...


class Checkout(Protocol):
    def fetch(self, check: bool = False) -> tuple[int, str]: ...


class StageLoop(Protocol):
    def run(self, plan: PlanData, i: int, state: RoundState | None = None) -> str: ...


class Pictures(Protocol):
    @property
    def stale(self) -> bool: ...
    def shot_methods(self) -> Methods: ...
    def render_shots(self, reqs: Sequence[Open], rnd: int) -> tuple[list[str], list[str]]: ...


class Look(Protocol):
    @property
    def last_reqs(self) -> list[Open]: ...
    @property
    def done(self) -> int: ...


class Review(Protocol):
    @property
    def unchecked(self) -> list[Open]: ...


class Judge(Protocol):
    def is_look(self, u: Open) -> bool: ...


class OwnerLook(Protocol):
    def file_owner_look(self) -> None: ...


class Reload(Protocol):
    def safe_point(self, step: str) -> None: ...


class Resume(Protocol):
    def point(self) -> tuple[PlanData | None, int, RoundState | None]: ...


class Delegation(Protocol):
    def route(self) -> None: ...


class Router(Protocol):
    @property
    def contract_no(self) -> int: ...


class Tree(Protocol):
    def reset(self, bead: Bead) -> None: ...


class AskFlow(Protocol):
    def check(self) -> None: ...


class Checkpoints(Protocol):
    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "") -> None: ...


class Records(Protocol):
    def log_run(self) -> None: ...


class Log(Protocol):
    def note(self, text: str) -> object: ...
    def warn(self, text: str) -> object: ...


class Halt(Protocol):
    def is_set(self) -> bool: ...


class Budget(Protocol):
    labels: list[str]


class Answered(Protocol):
    @property
    def ask_class(self) -> AskClass: ...


class RunHost[T](CrashHost, Protocol):
    bead_title: str
    bead_parent: str
    scope: str
    stats: dict[str, int]
    @property
    def state(self) -> RunState: ...
    @property
    def store(self) -> Beads: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def stop_pending(self) -> bool: ...
    @property
    def halt(self) -> Halt: ...
    @property
    def delegation(self) -> Delegation: ...
    @property
    def route(self) -> str: ...
    @property
    def refusal(self) -> Refusal | None: ...
    @property
    def contract(self) -> Open: ...
    @property
    def router(self) -> Router: ...
    @property
    def tree(self) -> Tree: ...
    @property
    def budget(self) -> Budget: ...
    @property
    def ask_flow(self) -> AskFlow: ...
    @property
    def planner(self) -> Planner[T]: ...
    @property
    def answered(self) -> Answered | None: ...
    @property
    def pictures(self) -> Pictures: ...
    @property
    def look(self) -> Look: ...
    @property
    def dry(self) -> bool: ...
    @property
    def verifier(self) -> Verifier: ...
    @property
    def review(self) -> Review: ...
    @property
    def judge(self) -> Judge: ...
    @property
    def lander(self) -> Lander: ...
    @property
    def owner_look(self) -> OwnerLook: ...
    @property
    def resume(self) -> Resume: ...
    @property
    def records(self) -> Records: ...
    @property
    def rebase(self) -> Rebase: ...
    @property
    def salvage(self) -> Salvage: ...
    @property
    def restart(self) -> Restart: ...
    @property
    def reload(self) -> Reload: ...
    @property
    def replan_first(self) -> bool: ...
    @property
    def wt(self) -> str: ...
    @property
    def stage_loop(self) -> StageLoop: ...
    @property
    def checkpoints(self) -> Checkpoints: ...
    @property
    def checkout(self) -> Checkout: ...
    @property
    def stuck_why(self) -> str: ...
    @property
    def log(self) -> Log: ...


class RunBody[T]:
    def __init__(self, host: RunHost[T], history: HeadHistory, beat: Callable[[], None]) -> None:
        self.host, self.history, self.beat = host, history, beat

    def run(self, hb: LeaseLike, end: Ended) -> None:
        host = self.host
        bead = self.begin(hb)
        plan, i, state = self.prepare(bead)
        self.stages(plan, i, state)
        if host.pictures.stale and host.look.last_reqs and host.pictures.shot_methods() and not host.dry:
            # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
            host.log.note("rendering the last shots again: code changed since the pictures were made")
            host.pictures.render_shots(host.look.last_reqs, host.look.done + 1)
        gaps = host.verifier.run([u for u in host.review.unchecked if u["kind"] in UNCHECKED_KINDS or host.judge.is_look(u)])
        if gaps:
            what = "; ".join("{} ({}{})".format(u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps)
            raise Blocked("verify: before land, the workers could not check: " + what,
                            askspecs.external_fact([u["what"] for u in gaps]), kind=Kind.ASK_DECISION)
        try:
            sha = host.lander.finish(bead)
        except (Blocked, fence.Fenced):
            raise
        except Exception as err:
            done = parked_crash(host, Step.LAND, err)
            raise Blocked(done.detail, kind=done.kind) from err
        end.outcome = oc.make(Kind.LANDED, sha=sha) if sha else oc.make(Kind.DONE)
        if sha:
            host.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
        # the checkpoint stays: the close drops it as its last effect, and until then it holds the outcome a restart finishes from

    def begin(self, hb: LeaseLike) -> Bead:
        """The bead, claimed and checked: the delegate there, the tree reset, the ask read, the acceptance known."""
        host = self.host
        if host.stop_pending or host.halt.is_set():  # stopped during the claim (run_bead) or before the engine ran
            raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        bead = beadtools.peek(host.store, host.bead)
        if not bead:
            raise Blocked(f"failed: bead {host.bead} not found", kind=Kind.FAULT_INFRA)
        host.bead_title, host.bead_parent = bead.title, bead.parent
        hb.start()
        self.beat()
        host.delegation.route()
        if not host.route:
            why = host.refusal or Refusal("not_installed")
            raise Blocked(f"failed: delegate refused the call setup ({why.kind} {why.detail})", kind=Kind.FAULT_CONTRACT_SKEW)
        problem = pin.exec_allow_problem(host.cfg.writer_exec_allow, host.cfg.writer_family, bead.labels,
                                         host.contract.get("contract", 0), host.contract.get("capabilities", []))
        if problem:
            raise Blocked(problem, kind=Kind.FAULT_CONTRACT_SKEW)
        host.log.note(f"workers: delegate {host.route} (contract {host.router.contract_no})")
        host.log.note("task-loop {}".format(ident.plugin_version() or "(unknown version)"))
        host.tree.reset(bead)
        host.budget.labels = list(bead.labels)
        host.ask_flow.check()
        host.planner.cap.grant()
        written = host.planner.cap.answered_words() if host.answered and host.answered.ask_class == AskClass.MISSING_CRITERIA else ""
        if not AcceptanceText.present(bead) and not written:
            raise Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=Kind.ASK_TICKET)
        host.scope = AcceptanceText.text(bead) or written
        return bead

    def prepare(self, bead: Bead) -> tuple[PlanData, int, RoundState | None]:
        """(plan, stage, state) to go on with: the checkpoint's, rebased onto the base, or a new plan."""
        host = self.host
        plan, i, state = host.resume.point()
        host.records.log_run()
        # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
        # resume rebases first, a plan to make or a stage to go on with (a consumer: 8 beads parked on 'just fmt-check-changed')
        at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
        moved = "" if at_land else host.rebase.onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
        if moved == "conflict-fixable":
            host.state.plan_data = host.state.plan_data or plan
            moved = host.salvage.salvage()
        if moved == "conflict" and host.restart.again(self.its_work()):
            plan, i, state = None, 0, None
        elif moved == "rebased" and plan is not None:
            host.state.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
        if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
            host.reload.safe_point("plan")
            plan, i, state = host.planner.take(host.planner.plan(again=host.replan_first)), 0, None
        return plan, i, state

    def its_work(self) -> str:
        host = self.host
        log = self.history.ahead_of(host.wt, host.cfg.base, 3).replace("\n", "; ")
        return f"Its work: {log}"

    def stages(self, plan: PlanData, i: int, state: RoundState | None) -> None:
        host = self.host
        while i < len(plan["stages"]):
            d = host.stage_loop.run(plan, i, state)
            state = None
            if d == "replan":
                plan = self.replan(i)
                i = 0
                continue
            host.state.accepted.append(i)
            host.state.done.append(plan["stages"][i]["goal"])
            i += 1
            host.lander.out.wip_push(i)  # before the checkpoint: its head is the pushed commit
            if i == len(plan["stages"]):
                host.state.pending_land_validation = ""  # every recovery stage passed checks and review
            host.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
            if i == len(plan["stages"]):
                host.reload.safe_point("land")  # the checkpoint says land: the close and the land run on the newest code
            else:
                self.on_top_of_base()

    def on_top_of_base(self) -> None:
        """tl-7y6.23: before each stage after the first the run works on top of the base: fetch, and only when the base moved past the
        branch, rebase it (the tree is clean: the stage was committed as wip). No move, no rebase: the check cache stays valid. A conflict
        gets the one fix round; if that fails the bead is blocked and the branch kept."""
        host = self.host
        if host.dry or host.checkout.fetch()[0]:  # (a failed fetch is the land's to report)
            return
        moved = host.rebase.onto_base(salvage=True, between=True)
        if moved == "conflict-fixable":
            moved = host.salvage.salvage()
        if moved == "conflict":
            raise blocked_for(f"failed: the task branch no longer fits {host.cfg.base} (it moved during the run); the branch is kept at "
                                "its last accepted stage, fix the conflict by hand, then rerun", "FAULT_LAND")
        if moved:
            host.state.stage_tree = ""  # the next stage's diff is measured from the new base

    def replan(self, i: int) -> PlanData:
        host = self.host
        if host.state.pending_land_validation:
            host.state.pending_land_validation += "\n" + host.stuck_why
            host.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write")
        host.state.replans += 1
        host.stats["replans"] = replans = host.state.replans
        if replans > host.cfg.max_replans + host.state.extra:
            raise host.planner.cap.blocked(f"stage {i + 1} stuck after {host.cfg.max_rounds} rounds. What failed: {host.stuck_why[:600]}")
        host.state.accepted = list[int]()
        return host.planner.take(host.planner.plan(again=True))
