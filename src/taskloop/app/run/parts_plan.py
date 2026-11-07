"""The plan, write and review side of a run: the planner and its briefs, the writer's stage loop and handoff, the reviewers."""
import json
from functools import cached_property

from taskloop.app.plan.briefs import Briefs
from taskloop.app.plan.cases import Cases
from taskloop.app.plan.planned import Planned
from taskloop.app.plan.planner import Planner
from taskloop.app.review.link_check import LinkCheck
from taskloop.app.review.verifier import Verifier
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.write.briefing import Briefing
from taskloop.app.write.handoff import Handoff
from taskloop.app.write.stage_loop import StageLoop
from taskloop.contracts import plancheck
from taskloop.contracts.paths import PLAN_FILE
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.wire import Open


class PlanParts(Plumbing):
    cases = cached_property(Cases)
    briefs = cached_property(Briefs)
    planner = cached_property(Planner)
    briefing = cached_property(Briefing)
    stage_loop = cached_property(StageLoop)
    link_check = cached_property(LinkCheck)
    verifier = cached_property(Verifier)

    @cached_property
    def hand(self) -> Handoff:
        return Handoff(self, self.git)

    def publish_plan(self) -> None:
        if self.plan_data:
            (self.run_dir / PLAN_FILE).write_text(json.dumps(plancheck.to_wire(self.plan_data), indent=1))

    def keep_draft(self, data: PlanData) -> None:
        self.plan_data = data

    def set_summary(self, text: str) -> None:
        self.plan_summary = text

    def count_plan(self) -> None:
        self.planned += 1

    def add_leftovers(self, items: list[Open]) -> None:
        self.leftovers.extend(items)

    def take_planned(self, p: Planned) -> PlanData:
        self.plan_data, self.plan_summary, self.planned = p.plan_data, p.summary, p.planned
        return p.plan_data
