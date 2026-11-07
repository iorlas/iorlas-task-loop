"""The run body over local stage capabilities and shared run state."""
from collections.abc import Callable

from tlkernel import askspecs, fence
from tlkernel import runoutcome as oc
from tlkernel.askenums import AskClass
from tlkernel.bead import Bead
from tlkernel.delegateport import Refusal
from tlkernel.enums import Step
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.reviewkinds import UNCHECKED_KINDS

from taskloop.app.pipeline.adapter_ports import PeekBead, Version
from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.pipeline.crash import CrashHost, parked_crash
from taskloop.app.pipeline.lifecycle import Ended, LeaseLike
from taskloop.app.pipeline.ports import HeadHistory
from taskloop.app.pipeline.run_roles import Delegating, GitMoves, Leasing, RunRecords, RunValues, Stages
from taskloop.domain.lanes import pin
from taskloop.domain.plan.matchers import AcceptanceText


class RunBody[T]:
    def __init__(self, leasing: Leasing, delegating: Delegating, stages: Stages[T], records: RunRecords,
                 moves: GitMoves, values: RunValues, crashes: CrashHost, history: HeadHistory,
                 beat: Callable[[], None], peek_bead: PeekBead, version: Version) -> None:
        self.leasing, self.delegating, self.stages_ports = leasing, delegating, stages
        self.records, self.moves, self.values, self.crashes = records, moves, values, crashes
        self.history, self.beat = history, beat
        self.peek_bead, self.version = peek_bead, version

    def run(self, hb: LeaseLike, end: Ended) -> None:
        bead = self.begin(hb)
        plan, i, state = self.prepare(bead)
        self.stages(plan, i, state)
        if (self.stages_ports.pictures.stale and self.stages_ports.look.last_reqs
                and self.stages_ports.pictures.shot_methods() and not self.leasing.dry):
            # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
            self.records.log.note("rendering the last shots again: code changed since the pictures were made")
            self.stages_ports.pictures.render_shots(self.stages_ports.look.last_reqs, self.stages_ports.look.done + 1)
        gaps = self.stages_ports.verifier.run([u for u in self.stages_ports.review.unchecked
                                               if u["kind"] in UNCHECKED_KINDS or self.stages_ports.judge.is_look(u)])
        if gaps:
            what = "; ".join("{} ({}{})".format(u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps)
            raise Blocked("verify: before land, the workers could not check: " + what,
                            askspecs.external_fact([u["what"] for u in gaps]), kind=Kind.ASK_DECISION)
        try:
            sha = self.stages_ports.lander.finish(bead)
        except (Blocked, fence.Fenced):
            raise
        except Exception as err:
            done = parked_crash(self.crashes, Step.LAND, err)
            raise Blocked(done.detail, kind=done.kind) from err
        end.outcome = oc.make(Kind.LANDED, sha=sha) if sha else oc.make(Kind.DONE)
        if sha:
            self.stages_ports.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
        # the checkpoint stays: the close drops it as its last effect, and until then it holds the outcome a restart finishes from

    def begin(self, hb: LeaseLike) -> Bead:
        """The bead, claimed and checked: the delegate there, the tree reset, the ask read, the acceptance known."""
        if self.leasing.stop_pending or self.leasing.halt.is_set():  # stopped during the claim (run_bead) or before the engine ran
            raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        bead = self.peek_bead(self.leasing.store, self.leasing.bead)
        if not bead:
            raise Blocked(f"failed: bead {self.leasing.bead} not found", kind=Kind.FAULT_INFRA)
        self.values.bead_title, self.values.bead_parent = bead.title, bead.parent
        hb.start()
        self.beat()
        self.delegating.delegation.route()
        if not self.delegating.route:
            why = self.delegating.refusal or Refusal("not_installed")
            raise Blocked(f"failed: delegate refused the call setup ({why.kind} {why.detail})", kind=Kind.FAULT_CONTRACT_SKEW)
        problem = pin.exec_allow_problem(self.leasing.cfg.writer_exec_allow, self.leasing.cfg.writer_family, bead.labels,
                                         self.delegating.contract.get("contract", 0), self.delegating.contract.get("capabilities", []))
        if problem:
            raise Blocked(problem, kind=Kind.FAULT_CONTRACT_SKEW)
        self.records.log.note(f"workers: delegate {self.delegating.route} (contract {self.delegating.router.contract_no})")
        self.records.log.note("task-loop {}".format(self.version() or "(unknown version)"))
        self.records.tree.reset(bead)
        self.records.budget.labels = list(bead.labels)
        self.records.ask_flow.check()
        self.stages_ports.planner.cap.grant()
        written = (self.stages_ports.planner.cap.answered_words()
                   if self.records.answered and self.records.answered.ask_class == AskClass.MISSING_CRITERIA else "")
        if not AcceptanceText.present(bead) and not written:
            raise Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=Kind.ASK_TICKET)
        self.values.scope = AcceptanceText.text(bead) or written
        return bead

    def prepare(self, bead: Bead) -> tuple[PlanData, int, RoundState | None]:
        """(plan, stage, state) to go on with: the checkpoint's, rebased onto the base, or a new plan."""
        plan, i, state = self.records.resume.point()
        self.records.records.log_run()
        # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
        # resume rebases first, a plan to make or a stage to go on with (a consumer: 8 beads parked on 'just fmt-check-changed')
        at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
        moved = "" if at_land else self.moves.rebase.onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
        if moved == "conflict-fixable":
            self.values.state.plan_data = self.values.state.plan_data or plan
            moved = self.moves.salvage.salvage()
        if moved == "conflict" and self.moves.restart.again(self.its_work()):
            plan, i, state = None, 0, None
        elif moved == "rebased" and plan is not None:
            self.values.state.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
        if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
            self.records.reload.safe_point("plan")
            plan, i, state = self.stages_ports.planner.take(self.stages_ports.planner.plan(again=self.values.replan_first)), 0, None
        return plan, i, state

    def its_work(self) -> str:
        log = self.history.ahead_of(self.moves.wt, self.leasing.cfg.base, 3).replace("\n", "; ")
        return f"Its work: {log}"

    def stages(self, plan: PlanData, i: int, state: RoundState | None) -> None:
        while i < len(plan["stages"]):
            d = self.stages_ports.stage_loop.run(plan, i, state)
            state = None
            if d == "replan":
                plan = self.replan(i)
                i = 0
                continue
            self.values.state.accepted.append(i)
            self.values.state.done.append(plan["stages"][i]["goal"])
            i += 1
            self.stages_ports.lander.out.wip_push(i)  # before the checkpoint: its head is the pushed commit
            if i == len(plan["stages"]):
                self.values.state.pending_land_validation = ""  # every recovery stage passed checks and review
            self.records.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write" if i < len(plan["stages"]) else "land")
            if i == len(plan["stages"]):
                self.records.reload.safe_point("land")  # the checkpoint says land: the close and the land run on the newest code
            else:
                self.on_top_of_base()

    def on_top_of_base(self) -> None:
        """tl-7y6.23: before each stage after the first the run works on top of the base: fetch, and only when the base moved past the
        branch, rebase it (the tree is clean: the stage was committed as wip). No move, no rebase: the check cache stays valid. A conflict
        gets the one fix round; if that fails the bead is blocked and the branch kept."""
        if self.leasing.dry or self.moves.checkout.fetch()[0]:  # (a failed fetch is the land's to report)
            return
        moved = self.moves.rebase.onto_base(salvage=True, between=True)
        if moved == "conflict-fixable":
            moved = self.moves.salvage.salvage()
        if moved == "conflict":
            raise blocked_for(f"failed: the task branch no longer fits {self.leasing.cfg.base} (it moved during the run); "
                                "the branch is kept at "
                                "its last accepted stage, fix the conflict by hand, then rerun", "FAULT_LAND")
        if moved:
            self.values.state.stage_tree = ""  # the next stage's diff is measured from the new base

    def replan(self, i: int) -> PlanData:
        if self.values.state.pending_land_validation:
            self.values.state.pending_land_validation += "\n" + self.values.stuck_why
            self.records.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write")
        self.values.state.replans += 1
        self.values.stats["replans"] = replans = self.values.state.replans
        if replans > self.leasing.cfg.max_replans + self.values.state.extra:
            raise self.stages_ports.planner.cap.blocked(
                f"stage {i + 1} stuck after {self.leasing.cfg.max_rounds} rounds. What failed: {self.values.stuck_why[:600]}")
        self.values.state.accepted = list[int]()
        return self.stages_ports.planner.take(self.stages_ports.planner.plan(again=True))
