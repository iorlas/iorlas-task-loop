"""The plan stage's hand-off to the pipeline."""
from dataclasses import dataclass

from taskloop.contracts.plancheck import PlanData


@dataclass(frozen=True, slots=True)
class Planned:
    """What Planner.plan returns; the pipeline stores it."""

    plan_data: PlanData
    summary: str
    planned: int
