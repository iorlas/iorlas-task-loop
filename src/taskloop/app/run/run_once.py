"""One run of the engine: claim checks, the stages, the land, and the close-out that always runs."""
from collections.abc import Callable
from typing import Any

from tlkernel import fence
from tlkernel.delegateport import Refusal
from tlkernel.enums import AskClass, Step
from tlkernel.envvars import EnvVar
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData, RoundState

from taskloop.adapters import beadtools, ident
from taskloop.app.land.gitcall import oneline
from taskloop.app.pipeline.crash import parked_crash
from taskloop.app.pipeline.lifecycle import Ended, LeaseLike, Lifecycle
from taskloop.app.release.closing import ReexecBook
from taskloop.app.slots.lease import Lease
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.lanes import pin
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.domain.review.kinds import UNCHECKED_KINDS


class RunOnce:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.lifecycle = Lifecycle(host, body=self.run, lease=self.lease, reexecs=ReexecBook(host.home))

    def lease(self, on_beat: Callable[[], None], on_death: Callable[[BaseException], None]) -> Lease:
        e = self.e
        return Lease(e.store, e.bead, e.env.bead(EnvVar.TASK_LOOP_SLOT_BEAD), on_beat=on_beat, on_death=on_death)

    def go(self) -> int:
        return self.lifecycle.go()

    def beat(self) -> None:
        self.lifecycle.beat()

    def beat_died(self, err: BaseException) -> None:
        self.lifecycle.beat_died(err)

    def run(self, hb: LeaseLike, end: Ended) -> None:
        e = self.e
        bead = self.begin(hb)
        plan, i, state = self.prepare(bead)
        self.stages(plan, i, state)
        if e.pictures.stale and e.look.last_reqs and e.pictures.shot_methods() and not e.dry:
            # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
            e.log.note("rendering the last shots again: code changed since the pictures were made")
            e.pictures.render_shots(e.look.last_reqs, e.look.done + 1)
        gaps = e.verifier.run([u for u in e.review.unchecked if u["kind"] in UNCHECKED_KINDS or e.judge.is_look(u)])
        if gaps:
            what = "; ".join("{} ({}{})".format(u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps)
            raise e.Blocked("verify: before land, the workers could not check: " + what,
                            askspecs.external_fact([u["what"] for u in gaps]), kind=Kind.ASK_DECISION)
        try:
            sha = e.lander.finish(bead)
        except (e.Blocked, fence.Fenced):
            raise
        except Exception as err:
            done = parked_crash(e, Step.LAND, err)
            raise e.Blocked(done.detail, kind=done.kind) from err
        end.outcome = oc.make(Kind.LANDED, sha=sha) if sha else oc.make(Kind.DONE)
        if sha:
            e.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
        # the checkpoint stays: the close drops it as its last effect, and until then it holds the outcome a restart finishes from

    def begin(self, hb: LeaseLike) -> Any:
        """The bead, claimed and checked: the delegate there, the tree reset, the ask read, the acceptance known."""
        e = self.e
        if e.stop_pending or e.halt.is_set():  # stopped during the claim (run_bead) or before the engine ran
            raise e.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        bead = beadtools.peek(e.store, e.bead)
        if not bead:
            raise e.Blocked(f"failed: bead {e.bead} not found", kind=Kind.FAULT_INFRA)
        e.bead_title, e.bead_parent = bead.title, bead.parent
        hb.start()
        self.beat()
        e.delegation.route()
        if not e.route:
            why = e.refusal or Refusal("not_installed")
            raise e.Blocked(f"failed: delegate refused the call setup ({why.kind} {why.detail})", kind=Kind.FAULT_CONTRACT_SKEW)
        problem = pin.exec_allow_problem(e.cfg.writer_exec_allow, e.cfg.writer_family, bead.labels,
                                         e.contract.get("contract", 0), e.contract.get("capabilities", []))
        if problem:
            raise e.Blocked(problem, kind=Kind.FAULT_CONTRACT_SKEW)
        e.log.note(f"workers: delegate {e.route} (contract {e.router.contract_no})")
        e.log.note("task-loop {}".format(ident.plugin_version() or "(unknown version)"))
        e.tree.reset(bead)
        e.budget.labels = list(bead.labels)
        e.ask_flow.check()
        e.planner.cap.grant()
        written = e.planner.cap.answered_words() if e.answered and e.answered.ask_class == AskClass.MISSING_CRITERIA else ""
        if not AcceptanceText.present(bead) and not written:
            raise e.Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=Kind.ASK_TICKET)
        e.scope = AcceptanceText.text(bead) or written
        return bead

    def prepare(self, bead: Any) -> tuple[PlanData, int, RoundState | None]:
        """(plan, stage, state) to go on with: the checkpoint's, rebased onto the base, or a new plan."""
        e = self.e
        plan, i, state = e.resume.point()
        e.records.log_run()
        # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
        # resume rebases first, a plan to make or a stage to go on with (a consumer: 8 beads parked on 'just fmt-check-changed')
        at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
        moved = "" if at_land else e.rebase.onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
        if moved == "conflict-fixable":
            e.plan_data = e.plan_data or plan
            moved = e.salvage.salvage()
        if moved == "conflict" and e.restart.again(self.its_work()):
            plan, i, state = None, 0, None
        elif moved == "rebased" and plan is not None:
            e.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
        if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
            e.reload.safe_point("plan")
            plan, i, state = e.planner.take(e.planner.plan(again=e.replan_first)), 0, None
        return plan, i, state

    def its_work(self) -> str:
        e = self.e
        log = oneline(e.git, e.wt, ["HEAD"], [e.cfg.base], 3).replace("\n", "; ")
        return f"Its work: {log}"

    def stages(self, plan: PlanData, i: int, state: RoundState | None) -> None:
        e = self.e
        while i < len(plan["stages"]):
            d = e.stage_loop.run(plan, i, state)
            state = None
            if d == "replan":
                plan = self.replan(i)
                i = 0
                continue
            e.accepted.append(i)
            e.done.append(plan["stages"][i]["goal"])
            i += 1
            e.lander.out.wip_push(i)  # before the checkpoint: its head is the pushed commit
            if i == len(plan["stages"]):
                e.pending_land_validation = ""  # every recovery stage passed checks and review
            e.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
            if i == len(plan["stages"]):
                e.reload.safe_point("land")  # the checkpoint says land: the close and the land run on the newest code
            else:
                self.on_top_of_base()

    def on_top_of_base(self) -> None:
        """tl-7y6.23: before each stage after the first the run works on top of the base: fetch, and only when the base moved past the
        branch, rebase it (the tree is clean: the stage was committed as wip). No move, no rebase: the check cache stays valid. A conflict
        gets the one fix round; if that fails the bead is blocked and the branch kept."""
        e = self.e
        if e.dry or e.checkout.fetch()[0]:  # (a failed fetch is the land's to report)
            return
        moved = e.rebase.onto_base(salvage=True, between=True)
        if moved == "conflict-fixable":
            moved = e.salvage.salvage()
        if moved == "conflict":
            raise e.blocked_for(f"failed: the task branch no longer fits {e.cfg.base} (it moved during the run); the branch is kept at "
                                "its last accepted stage, fix the conflict by hand, then rerun", "FAULT_LAND")
        if moved:
            e.stage_tree = ""  # the next stage's diff is measured from the new base

    def replan(self, i: int) -> Any:
        e = self.e
        if e.pending_land_validation:
            e.pending_land_validation += "\n" + e.stuck_why
            e.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write")
        e.replans += 1
        e.stats["replans"] = replans = e.replans
        if replans > int(e.cfg.max_replans) + e.extra:
            raise e.planner.cap.blocked(f"stage {i + 1} stuck after {e.cfg.max_rounds} rounds. What failed: {e.stuck_why[:600]}")
        e.accepted = list[int]()
        return e.planner.take(e.planner.plan(again=True))
