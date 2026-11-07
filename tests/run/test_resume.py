"""What a resume hands the stage loop once the decision is made: where it goes on, and what it puts back in the engine."""
import sys
from pathlib import Path
from types import SimpleNamespace

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.pipeline_ports import FakeHeadHistory

from taskloop.app.pipeline.decide import Decision
from taskloop.app.pipeline.resume import Resume
from taskloop.app.pipeline.review_glue import ReviewGlue
from taskloop.app.review.state import ReviewLive
from taskloop.app.run.state import state_names
from tlkernel import wire
from tlkernel.answers import WriteAnswerLook
from tlkernel.checkpoint import Checkpoint, RunState, StageProgress
from tlkernel.checks import CheckRun
from tlkernel.plancheck import PlanData

PLAN: PlanData = {"summary": "two stages", "stages": [{"goal": "a", "files": [], "checks": []}, {"goal": "b", "files": [], "checks": []}]}

ANSWER = WriteAnswerLook(summary="s", checks_run=[], question="", options=[], decided="", bad_checks=[], new_cases=[], unchecked=[],
                         logic_only="")


class Host(SimpleNamespace):
    last_run: CheckRun | None
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.log = SimpleNamespace(note=self.notes.append)
        self.review = ReviewLive()
        self.state = RunState()
        self.plan_summary, self.published = "", 0
        self.run_id, self.last_run, self.stores = "r2", None, SimpleNamespace()

    def publish_plan(self) -> None:
        self.published += 1


def ck(step="write", stage=1) -> Checkpoint:
    return Checkpoint(bead="t-1", run="r1", t=0.0, branch="task/t-1", head="h1", step=step, stage=stage, rounds=2, n=3, feedback="fb",
                      state=RunState(plan_data=PLAN, accepted=[0]))


class Apply(Case):
    def test_a_mid_stage_resume_goes_on_at_the_same_stage_and_round(self):
        h = Host()
        plan, stage, state = Resume(h, FakeHeadHistory(), ReviewGlue(h), state_names()).apply(ck(), Decision(kind="resume", stage=1))
        assert (plan, stage, state) == (PLAN, 1, {"rounds": 2, "n": 3, "feedback": "fb"})
        assert (h.state.plan_data, h.plan_summary, h.state.accepted, h.published) == (PLAN, "two stages", [0], 1)

    def test_a_review_checkpoint_hands_the_stage_its_progress_and_the_check_run(self):  # tl-q3ma
        h = Host()
        run = SimpleNamespace()
        written: list[object] = []
        h.stores = SimpleNamespace(check_run=lambda rid, _: SimpleNamespace(get=lambda: run, write=written.append))
        progress = StageProgress(write=ANSWER)
        _, _, state = Resume(h, FakeHeadHistory(), ReviewGlue(h), state_names()).apply(
            ck(step="review").replace(progress=progress), Decision(kind="resume", stage=1))
        assert state == {"rounds": 2, "n": 3, "feedback": "fb", "review_from": wire.dump(progress)}
        assert (h.last_run, written) == (run, [run])

    def test_a_review_checkpoint_without_its_check_run_goes_on_at_the_write(self):
        h = Host()
        h.stores = SimpleNamespace(check_run=lambda rid, _: SimpleNamespace(get=lambda: None))
        progress = StageProgress(write=ANSWER)
        _, _, state = Resume(h, FakeHeadHistory(), ReviewGlue(h), state_names()).apply(
            ck(step="review").replace(progress=progress), Decision(kind="resume", stage=1))
        assert state == {"rounds": 2, "n": 3, "feedback": "fb"}

    def test_every_stage_accepted_goes_straight_to_land_with_no_stage_state(self):
        h = Host()
        plan, stage, state = Resume(h, FakeHeadHistory(), ReviewGlue(h), state_names()).apply(
            ck(step="land", stage=2), Decision(kind="land", stage=2, why="confirmed"))
        assert (plan, stage, state) == (PLAN, 2, None)
        assert "straight to land" in h.notes[-1]
