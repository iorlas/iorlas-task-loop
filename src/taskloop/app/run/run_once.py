"""One run of the engine: claim checks, the stages, the land, and the close-out that always runs."""
import contextlib
from dataclasses import dataclass, field
from typing import Any

from taskloop.adapters import beadtools, ident
from taskloop.adapters import delegate as dg
from taskloop.app.release import reexec
from taskloop.app.run import ended as stored_end
from taskloop.app.run import requests
from taskloop.app.run.reload import Exec
from taskloop.app.slots.lease import Lease
from taskloop.contracts import env as penv
from taskloop.contracts import fence
from taskloop.contracts.enums import AskClass
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.log import Beat
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.domain.review.kinds import UNCHECKED_KINDS


@dataclass
class Ended:
    """How the run ended, as the close step needs it: the one RunOutcome (its kind, text, land commit and ask)."""
    outcome: oc.RunOutcome = field(default_factory=lambda: oc.make(oc.Kind.FAULT_ENGINE))


class RunOnce:
    def __init__(self, host: Any) -> None:
        self.e = host

    def go(self) -> int:
        e = self.e
        end = Ended()
        hb = Lease(e.store, e.bead, penv.ambient_bead(EnvVar.TASK_LOOP_SLOT_BEAD), on_beat=self.beat)
        ck = e.checkpoints.read()
        e.prev_ck = ck.run if ck else ""
        try:
            if e.dead is not None:  # the last run died inside its close: this process only finishes it
                self.finish_dead(end)
            else:
                self.run(hb, end)
        except e.Blocked as b:
            end.outcome = b.outcome
            if b.kind is oc.Kind.PAUSE_KILLED and e.requests.stopped:  # the stop flag was the owner's request, not a SIGTERM
                end.outcome = oc.make(b.kind, requests.STOPPED_WHY)
        except fence.Fenced as f:  # the bead or the slot was taken again: this run writes nothing more
            e.fenced = f.why
            end.outcome = oc.make(oc.Kind.FAULT_ENGINE, f.why)
        except Exec:
            pass  # the process image is gone; nothing below runs in a real exec
        except Exception as err:  # the close-out must run whatever broke
            end.outcome = oc.make(oc.Kind.FAULT_ENGINE, f"failed: engine error {type(err).__name__}: {err}")
        finally:
            self.close_out(hb, end)
        return 0 if e.moved or end.outcome.finished else 2

    def finish_dead(self, end: Ended) -> None:
        """The state the close's effects read comes back from the dead run's checkpoint; the outcome is the one it kept."""
        e = self.e
        ck = e.dead
        assert ck is not None and ck.ended is not None
        end.outcome, _, _ = stored_end.loaded(ck.ended)
        e.resume.restore(ck, late=True)
        e.leftovers = [dict(lo) for lo in ck.ended.leftovers]  # in memory only until the close stored them
        e.plan_data = ck.state.plan_data
        e.plan_summary = (e.plan_data or {}).get("summary", "")
        e.accepted = list(ck.state.accepted)
        e.branch = ck.branch

    def beat(self) -> None:
        """The run's proof of life in its log (runlife.liveness reads it), then the stuck tick and the owner's stop; a log that cannot
        be written must not kill the beat thread."""
        with contextlib.suppress(OSError):
            self.e.log.emit(Beat())
        self.e.stuck.tick()
        self.e.requests.at_beat()

    def run(self, hb: Any, end: Ended) -> None:
        e = self.e
        bead = self.begin(hb)
        plan, i, state = self.prepare(bead)
        self.stages(plan, i, state)
        if e.render_stale and e.last_reqs and e.pictures.shot_methods() and not e.dry:
            # code changed after the last render (a fix round past the render rounds): the pictures that land show the tree
            e.log.note("rendering the last shots again: code changed since the pictures were made")
            e.pictures.render_shots(e.last_reqs, e.look_done + 1)
        gaps = e.verifier.run([u for u in e.unchecked if u["kind"] in UNCHECKED_KINDS or e.judge.is_look(u)])
        if gaps:
            what = "; ".join("{} ({}{})".format(u["what"], u["kind"], ("; " + u["why"]) if u.get("why") else "") for u in gaps)
            raise e.Blocked("verify: before land, the workers could not check: " + what,
                            askspecs.external_fact([u["what"] for u in gaps]), kind=oc.Kind.ASK_DECISION)
        sha = e.lander.finish(bead)
        end.outcome = oc.make(oc.Kind.LANDED, sha=sha) if sha else oc.make(oc.Kind.DONE)
        if sha:
            e.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
        # the checkpoint stays: the close drops it as its last effect, and until then it holds the outcome a restart finishes from

    def begin(self, hb: Any) -> Any:
        """The bead, claimed and checked: the delegate there, the tree reset, the ask read, the acceptance known."""
        e = self.e
        if e.stop_pending or e.halt.is_set():  # stopped during the claim (run_bead) or before the engine ran
            raise e.Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
        bead = beadtools.peek(e.store, e.bead)
        if not bead:
            raise e.Blocked(f"failed: bead {e.bead} not found", kind=oc.Kind.FAULT_INFRA)
        e.bead_title, e.bead_parent = bead.title, bead.parent
        hb.start()
        self.beat()
        e.delegation.route()
        if not e.route:
            why = e.refusal or dg.Refusal("not_installed")
            raise e.Blocked(f"failed: the engine needs the iorlas-delegate plugin that speaks contract {dg.CONTRACT} "
                            f"({why.kind} {why.detail}); update both: claude plugin update iorlas-delegate@iorlas-marketplace",
                            kind=oc.Kind.FAULT_CONTRACT_SKEW)
        e.log.note(f"workers: delegate {e.route} (contract {dg.CONTRACT})")
        e.log.note("task-loop {}".format(ident.plugin_version() or "(unknown version)"))
        e.tree.reset(bead)
        e.budget.labels = list(bead.labels)
        e.ask_flow.check()
        e.planner.cap.grant()
        written = e.planner.cap.answered_words() if e.answered and e.answered.ask_class == AskClass.MISSING_CRITERIA else ""
        if not AcceptanceText.present(bead) and not written:
            raise e.Blocked("ticket: the bead has no acceptance criteria", askspecs.missing_criteria(), kind=oc.Kind.ASK_TICKET)
        e.scope = AcceptanceText.text(bead) or written
        return bead

    def prepare(self, bead: Any) -> tuple[Any, int, Any]:
        """(plan, stage, state) to go on with: the checkpoint's, rebased onto the base, or a new plan."""
        e = self.e
        plan, i, state = e.resume.point()
        e.records.log_run()
        # tl-fsj: the configured checks come from the base's config, so the tree they run on must have what the base has; every
        # resume rebases first, a plan to make or a stage to go on with (lifesim: 8 beads parked on 'just fmt-check-changed')
        at_land = plan is not None and (i >= len(plan["stages"]) or (state or {}).get("fix"))  # a conflict there is the writer's fix round
        moved = "" if at_land else e.rebase.onto_base(salvage=plan is not None)  # (no plan: nothing accepted to salvage)
        if moved == "conflict-fixable":
            e.plan_data = e.plan_data or plan
            moved = e.rebase.salvage()
        if moved == "conflict" and e.rebase.start_again(self.its_work()):
            plan, i, state = None, 0, None
        elif moved == "rebased" and plan is not None:
            e.stage_tree = ""  # the stage's diff starts at the base now: the rebase moved what it was measured from
        if plan is None:  # a move here loses nothing: the new image reads the same checkpoint (or none) and plans
            e.reload.safe_point("plan")
            plan, i, state = e.planner.plan(again=e.replan_first), 0, None
        return plan, i, state

    def its_work(self) -> str:
        e = self.e
        log = (e.git("log", "--oneline", "-n", "3", f"{e.cfg.base}..HEAD") or "").replace("\n", "; ")
        return f"Its work: {log}"

    def stages(self, plan: Any, i: int, state: Any) -> None:
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
            moved = e.rebase.salvage()
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
        return e.planner.plan(again=True)

    def close_out(self, hb: Any, end: Ended) -> None:
        e = self.e
        if e.moved:
            hb.stop()
            return
        with e.stop_deferred():  # a stop here would skip the close: no trace, no bead update
            if e.landed_sha and end.outcome.kind is not oc.Kind.LANDED:  # stopped after the push: on the base, close it as landed
                e.warn(f"{end.outcome.detail or end.outcome.word} after the land went through; closing it landed")
                end.outcome = oc.make(oc.Kind.LANDED, sha=e.landed_sha)
            hb.stop()
            e.fenced = e.fenced or fence.stale(e.store, e.claim)
            if e.fenced:  # a run that lost its lease closes nothing: the bead, its checkpoint and its trace are the new holder's
                e.warn(f"fenced out: {e.fenced}; the bead, its checkpoint and the slot are left to the run that holds them")
                return
            e.stuck.tick()  # the last tick: a run that stops on its third same red says it before its Close
            e.requests.drop()  # what the run did not take is for a run that ended
            reexec.drop_reexec(e.bead)  # a run that ended is no crash after an exec
            if end.outcome.kind is oc.Kind.PAUSE_NETWORK and not e.dry:
                e.reload.save_net_pause()
            e.why = end.outcome.detail
            e.closer.close(end.outcome)
