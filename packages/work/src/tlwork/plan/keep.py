"""What the planner keeps of the run's plan, written where collaborators read it at the point it happens: the early save of a finished
draft (d5f.38), publish_plan, the ledger and the cases all read the plan while `Planner.plan` is still running. The planner holds no engine
write of its own; the pipeline stores what `plan` returns through `take`."""
from typing import Protocol

from tlkernel.plancheck import PlanData
from tlkernel.stagefacts import LeftoverSink
from tlkernel.wire import Open

from tlwork.plan.planned import Planned


class PlanFields(Protocol):
    """The run's plan fields the keeper writes (RunState's `plan_data`, `plan_summary`, and `planned`)."""

    plan_data: PlanData | None
    plan_summary: str
    planned: int


class PlanKeeper:
    def __init__(self, fields: PlanFields, sink: LeftoverSink) -> None:
        self.fields, self.sink = fields, sink

    def draft(self, data: PlanData) -> None:
        self.fields.plan_data = data

    def summary(self, text: str) -> None:
        self.fields.plan_summary = text

    def count(self) -> None:
        self.fields.planned += 1

    def leftovers(self, items: list[Open]) -> None:
        self.sink.extend(items)

    def take(self, p: Planned) -> PlanData:
        self.fields.plan_data, self.fields.plan_summary, self.fields.planned = p.plan_data, p.summary, p.planned
        return p.plan_data
