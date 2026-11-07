"""What the plan stage keeps between its steps and does not save: each once-per-run send-back the planner has used, and whether the
re-plan cap was raised. The checkpointed plan fields (`plan_data`, `planned`, `extra`, `brief_hash`, `snap`) are the run state's, so
they stay engine attributes (docs/design/b-plan.md, slice 2)."""


class PlanState:
    def __init__(self) -> None:
        self.cap_granted = False
        self.assumed = False  # tl-ntp: the planner was sent back once to plan on assumptions
        self.decided = False  # the planner was sent back once with the requirement that answers its question
        self.visual_back = False  # the planner was sent back once for a visual path touched with no look-objective, taste or show case
