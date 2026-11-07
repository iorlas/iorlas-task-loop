"""The plan stage's amendment context, kept for a resumed plan or cleared on restart."""

from tlkernel.plancheck import PlanData


class AmendState:
    def __init__(self) -> None:
        self.old_plan: PlanData | None = None
        self.text = ""
        self.why = ""
        self.amended = False  # work exists before the amended plan's first stage

    def resume_into(self, old_plan: PlanData | None, why: str, text: str | None = None) -> None:
        self.old_plan = old_plan
        self.why = why
        if text is not None:
            self.text = text

    def clear(self) -> None:
        self.old_plan = None
        self.why = ""
        self.text = ""
        self.amended = False
