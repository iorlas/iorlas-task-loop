"""Resume: gather the world, ask `resume_decision`, and apply the answer to the engine (its state, its notes, replan.md)."""

import copy
from pathlib import Path
from typing import Any

from taskloop.app.run.decide import CONFIRMED, OUTSIDE, Decision, World, resume_decision, stage_count
from taskloop.app.run.review_glue import apply_review
from taskloop.app.run.state import state_names
from taskloop.contracts import plancheck
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.enums import AskClass
from taskloop.domain.plan import brief

KEEP_FOR_ACTIVE = ("plan_data", "accepted", "extra", "planner_ref", "brief_hash", "snap", "review")  # restored one by one, not copied over
LATE = (
    "done",
    "replans",
    "fixes",
    "denials",
    "stage_tree",
    "writer_said",
    "accepted_new",
    "writer",
    "writer_family",
    "writer_fallback",
    "fallback_lane",
)  # only a checkpoint this engine left (HEAD is where it was) hands these on
GATE_NOTE = (
    "Every stage was accepted, then the gate failed on the tree rebased onto the latest base (often another task landed "
    "first). Plan the fix.\n\n"
)
VERIFY_NOTE = "A push retry's validation fix did not pass checks and review. Plan the fix before landing.\n\n"


class Resume:
    def __init__(self, host: Any) -> None:
        self.e = host

    def point(self) -> tuple[Any, int, Any]:
        """(plan, stage index, stage state) from the last run's checkpoint, or (None, 0, None) to plan afresh. A tree changed since
        (someone edited the branch) amends the plan; a changed bead keeps the accepted stages and amends the rest; otherwise the
        run goes on at the same stage and round, with the same writer thread, or straight to land when every stage was accepted."""
        e = self.e
        e.replan_first = False
        ck = e.checkpoints.read()
        w = self.world(ck)
        d = resume_decision(ck, w)
        e.ck_run = "" if ck is None or e.fresh else ck.run
        if d.drop:
            e.checkpoints.drop()
        if ck is None or d.kind == "fresh":
            return None, 0, None
        self.restore(ck, late=d.why != OUTSIDE)
        e.resumed = d.why != OUTSIDE
        if d.kind in ("resume", "land"):
            self.note_kept(ck, w)
        return self.apply(ck, d)

    def note_kept(self, ck: Checkpoint, w: World) -> None:
        """The bead or the owner's answer moved but nothing the plan reads changed: say the plan is kept and the planner not called."""
        if w.answer_given and not w.answer_words and ck.state.brief_hash == w.brief_hash and w.brief_diff is not None:
            self.e.log.note(f"the owner's answer ({w.answer_action}) only asks for a rerun: keeping the plan, no planner run")
        elif ck.state.brief_hash != w.brief_hash:
            self.e.log.note(
                f"the bead changed since the checkpoint of {ck.run}, but nothing the plan reads: keeping the plan, no planner run"
            )

    def world(self, ck: Checkpoint | None) -> World:
        e = self.e
        a = e.answered
        given = a is not None and a.answer is not None
        words = e.planner.cap.answered_words() if a is not None or ck is not None else ""
        snap_diff = quiet = req = None
        if ck is not None and ck.state.snap:
            snap_diff = brief.diff(ck.state.snap, e.snap, words)
            quiet = brief.diff(ck.state.snap, e.snap, words, comments=False)
            req = brief.diff(ck.state.snap, e.snap, "", comments=False)
        return World(
            fresh=e.fresh,
            branch=e.git("symbolic-ref", "--short", "-q", "HEAD"),
            head=e.git("rev-parse", "HEAD"),
            parent=e.git("rev-parse", "HEAD~1") if e.left_dirty else "",
            left_dirty=e.left_dirty,
            brief_hash=e.brief_hash,
            answered=a is not None,
            answer_given=given,
            answer_external_fact=a is not None and a.ask_class == AskClass.EXTERNAL_FACT,
            answer_confirms=given and a is not None and a.answer is not None and a.answer.action == "confirm",
            answer_words=words,
            answer_id=a.id if a is not None else "",
            answer_action=a.answer.action if given and a is not None and a.answer is not None else "",
            brief_diff=snap_diff,
            brief_diff_quiet=quiet,
            brief_diff_req=req,
            missing_stage=self.missing(ck) if ck is not None else None,
        )

    def missing(self, ck: Checkpoint) -> int | None:
        n = stage_count(ck)
        plan = ck.state.plan_data or {}
        plancheck.parse(plan)  # a saved plan comes back as dicts: its checks are parsed again
        return self.e.cases.promised_missing(plan, n if (ck.step == "land" or ck.stage >= n) else ck.stage) if plan else None

    def restore(self, ck: Checkpoint, late: bool) -> None:
        """The checkpoint's state into the engine: what every resume keeps, and (HEAD is the engine's) what only a resume keeps."""
        e, saved = self.e.state, copy.deepcopy(ck.state)
        for name in state_names():
            if name not in KEEP_FOR_ACTIVE and (late or name not in LATE):
                setattr(e, name, getattr(saved, name))
        apply_review(self.e, saved.review, unchecked=False, late=late)
        e.extra = e.extra + saved.extra
        e.planner_ref = saved.planner_ref or e.planner_ref
        self.e.pending_land_validation = saved.pending_land_validation or (ck.feedback if ck.step == "land-verify-red" else "")

    def apply(self, ck: Checkpoint, d: Decision) -> tuple[Any, int, Any]:
        e = self.e
        plan = ck.state.plan_data
        if plan:
            plancheck.parse(plan)  # a saved plan comes back as dicts: its checks are parsed again
        if d.kind in ("amend", "replan"):
            return self.amend(ck, d)
        e.plan_data, e.plan_summary, e.accepted = plan, (plan or {})["summary"], list(ck.state.accepted)
        e.publish_plan()
        if d.redo_from is not None:
            return self.redo(ck, d)
        if d.kind == "land":
            if d.why != CONFIRMED:
                apply_review(e, ck.state.review, unchecked=True)  # still unproven: verified again before land
            e.log.note(f"resuming {ck.run}: every stage was accepted, going straight to land")
            return plan, d.stage, None
        e.log.note(f"resuming {ck.run} at stage {ck.stage + 1}/{stage_count(ck)}, round {ck.rounds + 1} (write {ck.n + 1})")
        return plan, ck.stage, {"rounds": ck.rounds, "n": ck.n, "feedback": ck.feedback}

    def redo(self, ck: Checkpoint, d: Decision) -> tuple[Any, int, Any]:
        """A file a stage promised is gone (the resume is in another slot): that stage runs again."""
        e, again = self.e, d.stage
        e.log.note(f"resuming {ck.run}: a file stage {again + 1} promised is missing, so that stage runs again")
        e.accepted = [k for k in e.accepted if k < again]
        redo = {st["goal"] for st in (ck.state.plan_data or {})["stages"][again:]}
        e.done = [g for g in e.done if g not in redo]
        e.unchecked = list[dict[str, Any]]()
        return ck.state.plan_data, again, None

    def amend(self, ck: Checkpoint, d: Decision) -> tuple[Any, int, Any]:
        """The plan is made again: the old one is kept for the planner to amend, with why and what changed."""
        e = self.e
        if d.verify_answer:
            e.plan_data, e.plan_summary = ck.state.plan_data, (ck.state.plan_data or {})["summary"]
            e.verify_answer = d.verify_answer
            asked = e.answered.id if e.answered else ""
            e.log.note(f"the owner answered verify ask {asked} with more than a yes: planning what it asks, keeping {len(e.done)} stage(s)")
            return None, 0, None
        e.old_plan, e.amend_why = ck.state.plan_data, d.amend_why
        if d.kind == "replan":
            self.replan_note(ck)
            return None, 0, None
        if d.why == OUTSIDE:
            e.log.note(f"the branch changed since the checkpoint of {ck.run}: amending its plan")
            e.amend_text = self.outside_text(ck)
            return None, 0, None
        e.log.note(f"the bead changed since the checkpoint of {ck.run}: amending its plan, keeping {len(e.done)} accepted stage(s)")
        e.amend_text = d.amend_text + "\nAccepted stages (their work is in the tree): " + ("; ".join(e.done) or "none")
        return None, 0, None

    def replan_note(self, ck: Checkpoint) -> None:
        e = self.e
        gate = ck.step == "gate-red"
        e.log.note(
            f"the gate was red at land in {ck.run}: re-planning with its output, keeping {len(e.done)} accepted stage(s)"
            if gate
            else f"retry validation failed in {ck.run}: re-planning the unaccepted fix"
        )
        Path(e.run_dir / "replan.md").write_text((GATE_NOTE + ck.gate_tail) if gate else (VERIFY_NOTE + ck.feedback))
        e.replan_first = True

    def outside_text(self, ck: Checkpoint) -> str:
        e = self.e
        return (
            "The branch changed outside the engine since the old plan (commits after {}):\n{}\nNo stage of the old plan is known to "
            "be in the tree; read `git status` and the diff from the base.".format(
                ck.head[:12], (e.git("log", "--oneline", "-n", "15", f"{ck.head}..HEAD") or "(none)")[:800]
            )
        )
