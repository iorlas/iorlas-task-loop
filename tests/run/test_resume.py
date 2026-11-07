"""What a resume hands the stage loop once the decision is made: where it goes on, and what it puts back in the engine."""
import sys
from pathlib import Path
from types import SimpleNamespace

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.pipeline.decide import Decision
from taskloop.app.review.state import ReviewLive
from taskloop.app.run.resume import Resume
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.plancheck import PlanData

PLAN: PlanData = {"summary": "two stages", "stages": [{"goal": "a", "files": [], "checks": []}, {"goal": "b", "files": [], "checks": []}]}


class Host:
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.log = SimpleNamespace(note=self.notes.append)
        self.review = ReviewLive()
        self.plan_data, self.plan_summary, self.accepted, self.published = None, "", [], 0

    def publish_plan(self) -> None:
        self.published += 1


def ck(step="write", stage=1) -> Checkpoint:
    return Checkpoint(bead="t-1", run="r1", t=0.0, branch="task/t-1", head="h1", step=step, stage=stage, rounds=2, n=3, feedback="fb",
                      state=RunState(plan_data=PLAN, accepted=[0]))


class Apply(Case):
    def test_a_mid_stage_resume_goes_on_at_the_same_stage_and_round(self):
        h = Host()
        plan, stage, state = Resume(h).apply(ck(), Decision(kind="resume", stage=1))
        assert (plan, stage, state) == (PLAN, 1, {"rounds": 2, "n": 3, "feedback": "fb"})
        assert (h.plan_data, h.plan_summary, h.accepted, h.published) == (PLAN, "two stages", [0], 1)

    def test_every_stage_accepted_goes_straight_to_land_with_no_stage_state(self):
        h = Host()
        plan, stage, state = Resume(h).apply(ck(step="land", stage=2), Decision(kind="land", stage=2, why="confirmed"))
        assert (plan, stage, state) == (PLAN, 2, None)
        assert "straight to land" in h.notes[-1]
