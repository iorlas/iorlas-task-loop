"""The plan, write and review side of a run: the planner and its briefs, the writer's stage loop and handoff, the reviewers."""
import json
from functools import cached_property

from taskloop.app.run.plumbing import Plumbing
from taskloop.app.write.briefing import Briefing
from taskloop.app.write.stage_loop import StageLoop
from tlkernel import plancheck
from tlkernel.paths import PLAN_FILE


class PlanParts(Plumbing):
    briefing = cached_property(Briefing)
    stage_loop = cached_property(StageLoop)

    def publish_plan(self) -> None:
        if self.plan_data:
            (self.run_dir / PLAN_FILE).write_text(json.dumps(plancheck.to_wire(self.plan_data), indent=1))
