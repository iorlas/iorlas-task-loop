"""The plan, write and review side of a run: the planner and its briefs, the writer's stage loop and handoff, the reviewers."""
import json
from functools import cached_property

from tlkernel import plancheck
from tlkernel.paths import PLAN_FILE
from tlwork.api import Briefing, StageLoop

from taskloop.app.run.plumbing import Plumbing


class PlanParts(Plumbing):
    briefing = cached_property(Briefing)
    stage_loop = cached_property(StageLoop)

    def publish_plan(self) -> None:
        if self.plan_data:
            (self.run_dir / PLAN_FILE).write_text(json.dumps(plancheck.to_wire(self.plan_data), indent=1))
