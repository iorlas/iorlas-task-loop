"""What the planner keeps of the run's plan, written where collaborators read it at the point it happens: the early save of a finished
draft (d5f.38), publish_plan, the ledger and the cases all read the plan while `Planner.plan` is still running. The planner holds no engine
write of its own; the pipeline stores what `plan` returns through `take`."""
from typing import Protocol

from taskloop.app.plan.planned import Planned
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.wire import Open


class PlanFields(Protocol):
    """The run's plan fields the keeper writes (RunState's `plan_data`, `plan_summary`, `planned`, and the follow-ups to file)."""

    plan_data: PlanData | None
    plan_summary: str
    planned: int
    leftovers: list[Open]


class PlanKeeper:
    def __init__(self, fields: PlanFields) -> None:
        self.fields = fields

    def draft(self, data: PlanData) -> None:
        self.fields.plan_data = data

    def summary(self, text: str) -> None:
        self.fields.plan_summary = text

    def count(self) -> None:
        self.fields.planned += 1

    def leftovers(self, items: list[Open]) -> None:
        self.fields.leftovers.extend(items)

    def take(self, p: Planned) -> PlanData:
        self.fields.plan_data, self.fields.plan_summary, self.fields.planned = p.plan_data, p.summary, p.planned
        return p.plan_data
