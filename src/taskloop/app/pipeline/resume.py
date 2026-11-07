"""Resume: gather the world, ask `resume_decision`, and apply the answer to the engine (its state, its notes, replan.md)."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel import planbrief as brief
from tlkernel import plancheck, wire
from tlkernel.ask import Ask
from tlkernel.askenums import AskClass
from tlkernel.checkpoint import Checkpoint, RunState
from tlkernel.checks import CheckRun
from tlkernel.gitport import Git
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.wire import Open

from taskloop.app.pipeline.decide import CONFIRMED, OUTSIDE, Decision, World, resume_decision, stage_count
from taskloop.app.pipeline.ports import HeadHistory, ReviewRestore

KEEP_FOR_ACTIVE = ("plan_data", "accepted", "extra", "planner_ref", "brief_hash", "snap", "review")  # restored one by one, not copied over
LATE = (
    "done",
    "replans",
    "fixes",
    "denials",
    "stage_tree",
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


class ResumeCheckpoints(Protocol):
    def read(self) -> Checkpoint | None: ...
    def drop(self) -> None: ...
    def keep_pending(self) -> None: ...


class ResumeLog(Protocol):
    def note(self, text: str) -> int: ...


class ResumeCap(Protocol):
    def answered_words(self) -> str: ...


class ResumePlanner[T](Protocol):
    @property
    def cap(self) -> ResumeCap: ...
    def take(self, p: T) -> PlanData: ...
    def resume_draft(self, data: PlanData) -> T: ...


class ResumeCases(Protocol):
    def promised_missing(self, plan: PlanData, upto: int) -> int | None: ...


class ResumeReview(Protocol):
    unchecked: list[Open]


class ResumeAmend(Protocol):
    def resume_into(self, old_plan: PlanData | None, why: str, text: str | None = None) -> None: ...


class ResumeCheckRun(Protocol):
    def get(self) -> CheckRun | None: ...
    def write(self, rec: CheckRun) -> None: ...


class ResumeStores(Protocol):
    @property
    def check_run(self) -> Callable[[str, int | None], ResumeCheckRun]: ...


class ResumeHost[T](Protocol):
    replan_first: bool
    fresh: bool
    ck_run: str
    resumed: bool
    answered: Ask | None
    wt: str
    left_dirty: bool
    plan_summary: str
    last_run: CheckRun | None
    run_id: str
    run_dir: Path
    verify_answer: str

    @property
    def git(self) -> Git: ...
    @property
    def state(self) -> RunState: ...
    @property
    def checkpoints(self) -> ResumeCheckpoints: ...
    @property
    def log(self) -> ResumeLog: ...
    @property
    def planner(self) -> ResumePlanner[T]: ...
    @property
    def cases(self) -> ResumeCases: ...
    @property
    def stores(self) -> ResumeStores: ...
    @property
    def review(self) -> ResumeReview: ...
    @property
    def amend(self) -> ResumeAmend: ...
    def publish_plan(self) -> None: ...


class Resume[T]:
    def __init__(self, host: ResumeHost[T], history: HeadHistory, review: ReviewRestore, state_names: tuple[str, ...]) -> None:
        self.host, self.history, self.review, self.state_names = host, history, review, state_names

    def point(self) -> tuple[PlanData | None, int, RoundState | None]:
        """(plan, stage index, stage state) from the last run's checkpoint, or (None, 0, None) to plan afresh. A tree changed since
        (someone edited the branch) amends the plan; a changed bead keeps the accepted stages and amends the rest; otherwise the
        run goes on at the same stage and round, with the same writer thread, or straight to land when every stage was accepted."""
        host = self.host
        host.replan_first = False
        ck = host.checkpoints.read()
        w = self.world(ck)
        d = resume_decision(ck, w)
        host.ck_run = "" if ck is None or host.fresh else ck.run
        if d.drop:
            host.checkpoints.drop()
        if ck is None or d.kind == "fresh":
            host.checkpoints.keep_pending()
            return None, 0, None
        self.restore(ck, late=d.why != OUTSIDE)
        host.resumed = d.why != OUTSIDE
        if d.kind in ("resume", "land"):
            self.note_kept(ck, w)
        return self.apply(ck, d)

    def note_kept(self, ck: Checkpoint, w: World) -> None:
        """The bead or the owner's answer moved but nothing the plan reads changed: say the plan is kept and the planner not called."""
        if w.answer_given and not w.answer_words and ck.state.brief_hash == w.brief_hash and w.brief_diff is not None:
            self.host.log.note(f"the owner's answer ({w.answer_action}) only asks for a rerun: keeping the plan, no planner run")
        elif ck.state.brief_hash != w.brief_hash:
            self.host.log.note(
                f"the bead changed since the checkpoint of {ck.run}, but nothing the plan reads: keeping the plan, no planner run"
            )

    def world(self, ck: Checkpoint | None) -> World:
        host = self.host
        a = host.answered
        given = a is not None and a.answer is not None
        words = host.planner.cap.answered_words() if a is not None or ck is not None else ""
        snap_diff = quiet = req = None
        if ck is not None and ck.state.snap is not None and host.state.snap is not None:
            snap_diff = brief.diff(ck.state.snap, host.state.snap, words)
            quiet = brief.diff(ck.state.snap, host.state.snap, words, comments=False)
            req = brief.diff(ck.state.snap, host.state.snap, "", comments=False)
        return World(
            fresh=host.fresh,
            branch=host.git.branch(host.wt),
            head=host.git.rev_parse(host.wt, "HEAD"),
            parent=host.git.rev_parse(host.wt, "HEAD~1") if host.left_dirty else "",
            left_dirty=host.left_dirty,
            brief_hash=host.state.brief_hash,
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
        plancheck.parse_stored(plan)  # a saved plan comes back with its risks and cases as dicts: their checks are parsed again
        return self.host.cases.promised_missing(plan, n if (ck.step == "land" or ck.stage >= n) else ck.stage) if plan else None

    def restore(self, ck: Checkpoint, late: bool) -> None:
        """The checkpoint's state into the engine: what every resume keeps, and (HEAD is the engine's) what only a resume keeps."""
        host, saved = self.host, copy.deepcopy(ck.state)
        for name in self.state_names:
            if name not in KEEP_FOR_ACTIVE and (late or name not in LATE):
                setattr(host.state, name, getattr(saved, name))
        self.review.apply(saved.review, unchecked=False, late=late)
        host.state.extra = host.state.extra + saved.extra
        host.state.planner_ref = saved.planner_ref or host.state.planner_ref
        self.host.state.pending_land_validation = saved.pending_land_validation or (ck.feedback if ck.step == "land-verify-red" else "")
        self.host.checkpoints.keep_pending()

    def apply(self, ck: Checkpoint, d: Decision) -> tuple[PlanData | None, int, RoundState | None]:
        host = self.host
        plan = ck.state.plan_data
        if plan:
            plancheck.parse_stored(plan)  # a saved plan comes back with its risks and cases as dicts: their checks are parsed again
        if d.kind in ("amend", "replan"):
            return self.amend(ck, d)
        if ck.step == "plan" and plan is not None:
            host.log.note(f"resuming {ck.run}: validating the saved draft plan before any write")
            return host.planner.take(host.planner.resume_draft(plan)), 0, None
        host.state.plan_data, host.plan_summary, host.state.accepted = plan, (plan or {})["summary"], list(ck.state.accepted)
        host.publish_plan()
        if d.redo_from is not None:
            return self.redo(ck, d)
        if d.kind == "land":
            if d.why != CONFIRMED:
                self.review.apply(ck.state.review, unchecked=True)  # still unproven: verified again before land
            host.log.note(f"resuming {ck.run}: every stage was accepted, going straight to land")
            return plan, d.stage, None
        host.log.note(f"resuming {ck.run} at stage {ck.stage + 1}/{stage_count(ck)}, round {ck.rounds + 1} (write {ck.n + 1})")
        state: RoundState = {"rounds": ck.rounds, "n": ck.n, "feedback": ck.feedback}
        if ck.step == "review" and ck.progress is not None and ck.progress.write is not None:  # tl-q3ma
            host.last_run = host.stores.check_run(ck.run, None).get()
            if host.last_run is not None:
                host.stores.check_run(host.run_id, None).write(host.last_run)
                state["review_from"] = wire.dump(ck.progress)
        return plan, ck.stage, state

    def redo(self, ck: Checkpoint, d: Decision) -> tuple[PlanData | None, int, RoundState | None]:
        """A file a stage promised is gone (the resume is in another slot): that stage runs again."""
        host, again = self.host, d.stage
        host.log.note(f"resuming {ck.run}: a file stage {again + 1} promised is missing, so that stage runs again")
        host.state.accepted = [k for k in host.state.accepted if k < again]
        redo = {st["goal"] for st in (ck.state.plan_data or {})["stages"][again:]}
        host.state.done = [g for g in host.state.done if g not in redo]
        host.review.unchecked = []
        return ck.state.plan_data, again, None

    def amend(self, ck: Checkpoint, d: Decision) -> tuple[PlanData | None, int, RoundState | None]:
        """The plan is made again: the old one is kept for the planner to amend, with why and what changed."""
        host = self.host
        if d.verify_answer:
            host.state.plan_data, host.plan_summary = ck.state.plan_data, (ck.state.plan_data or {})["summary"]
            host.verify_answer = d.verify_answer
            asked = host.answered.id if host.answered else ""
            host.log.note(f"the owner answered verify ask {asked} with more than a yes: planning what it asks, "
                          f"keeping {len(host.state.done)} stage(s)")
            return None, 0, None
        host.amend.resume_into(ck.state.plan_data, d.amend_why)
        if d.kind == "replan":
            self.replan_note(ck)
            return None, 0, None
        if d.why == OUTSIDE:
            host.log.note(f"the branch changed since the checkpoint of {ck.run}: amending its plan")
            host.amend.resume_into(ck.state.plan_data, d.amend_why, self.outside_text(ck))
            return None, 0, None
        host.log.note(
            f"the bead changed since the checkpoint of {ck.run}: amending its plan, keeping {len(host.state.done)} accepted stage(s)"
        )
        text = d.amend_text + "\nAccepted stages (their work is in the tree): " + ("; ".join(host.state.done) or "none")
        host.amend.resume_into(ck.state.plan_data, d.amend_why, text)
        return None, 0, None

    def replan_note(self, ck: Checkpoint) -> None:
        host = self.host
        gate = ck.step == "gate-red"
        host.log.note(
            f"the gate was red at land in {ck.run}: re-planning with its output, keeping {len(host.state.done)} accepted stage(s)"
            if gate
            else f"retry validation failed in {ck.run}: re-planning the unaccepted fix"
        )
        Path(host.run_dir / "replan.md").write_text((GATE_NOTE + ck.gate_tail) if gate else (VERIFY_NOTE + ck.feedback))
        host.replan_first = True

    def outside_text(self, ck: Checkpoint) -> str:
        host = self.host
        return (
            "The branch changed outside the engine since the old plan (commits after {}):\n{}\nNo stage of the old plan is known to "
            "be in the tree; read `git status` and the diff from the base.".format(
                ck.head[:12], (self.history.since(host.wt, ck.head, 15) or "(none)")[:800]
            )
        )
