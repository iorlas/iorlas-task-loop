"""One run of the engine: claim checks, the stages, the land, and the close-out that always runs."""
import contextlib
import os
from dataclasses import dataclass
from typing import Any, cast

from taskloop.adapters import beadtools, ident
from taskloop.adapters import delegate as dg
from taskloop.app.release import reexec
from taskloop.app.run import outcomes, requests
from taskloop.app.run.reload import Exec
from taskloop.app.slots.lease import Lease
from taskloop.contracts.enums import AskClass
from taskloop.contracts.log import Beat
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.plan.matchers import AcceptanceText
from taskloop.domain.review.kinds import UNCHECKED_KINDS


@dataclass
class Ended:
    """How the run ended, as the close step needs it."""
    outcome: str = "failed"
    why: str = ""
    sha: str = ""
    spec: Any = None
    kind: Any = oc.Kind.FAULT_ENGINE


class RunOnce:
    def __init__(self, host: Any) -> None:
        self.e = host

    def go(self) -> int:
        e = self.e
        end = Ended()
        hb = Lease(e.store, e.bead, os.environ.get("TASK_LOOP_SLOT_BEAD", ""), on_beat=self.beat)
        ck = e.checkpoints.read()
        e.prev_ck = ck.run if ck else ""
        try:
            self.run(hb, end)
        except e.Blocked as b:
            end.kind = b.kind
            end.outcome = outcomes.outcome_for(end.kind, b.why)
            end.why, end.spec = b.why, b.spec
            if end.kind == oc.Kind.PAUSE_KILLED and e.requests.stopped:  # the stop flag was the owner's request, not a SIGTERM
                end.why = requests.STOPPED_WHY
        except Exec:
            pass  # the process image is gone; nothing below runs in a real exec
        except Exception as err:  # the close-out must run whatever broke
            end.outcome, end.why, end.kind = "failed", f"failed: engine error {type(err).__name__}: {err}", oc.Kind.FAULT_ENGINE
        finally:
            self.close_out(hb, end)
        return 0 if e.moved or end.outcome in ("landed", "done") else 2

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
        end.sha = e.lander.finish(bead)
        end.outcome = "landed" if end.sha else "done"
        end.kind = oc.Kind.LANDED if end.sha else oc.Kind.DONE
        if end.sha:
            e.owner_look.file_owner_look()  # before the checkpoint goes: a crash from here on still files it on resume
        e.checkpoints.drop()

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

    def replan(self, i: int) -> Any:
        e = self.e
        if e.pending_land_validation:
            e.pending_land_validation += "\n" + e.stuck_why
            e.checkpoints.save(stage=i, rounds=0, n=0, feedback="", step="write")
        e.replans += 1
        e.stats["replans"] = replans = e.replans
        if replans > int(e.cfg.max_replans) + e.extra:
            raise e.planner.cap.blocked(f"stage {i + 1} stuck after {e.cfg.max_rounds} rounds. What failed: {e.stuck_why[:600]}")
        e.accepted = cast(list[int], [])
        return e.planner.plan(again=True)

    def close_out(self, hb: Any, end: Ended) -> None:
        e = self.e
        if e.moved:
            hb.stop()
            return
        with e.stop_deferred():  # a stop here would skip the close: no trace, no bead update
            if e.landed_sha and end.outcome != "landed":  # stopped after the push: on the base, close it as landed
                e.warn(f"{end.why or end.outcome} after the land went through; closing it landed")
                end.outcome, end.why, end.sha, end.spec, end.kind = "landed", "", e.landed_sha, None, oc.Kind.LANDED
            hb.stop()
            e.stuck.tick()  # the last tick: a run that stops on its third same red says it before its Close
            e.requests.drop()  # what the run did not take is for a run that ended
            reexec.drop_reexec(e.bead)  # a run that ended is no crash after an exec
            if end.kind == oc.Kind.PAUSE_NETWORK and not e.dry:
                e.reload.save_net_pause()
            e.outcome, e.why = end.outcome, end.why
            e.closer.close(end.outcome, end.why, end.sha, end.spec, end.kind)
