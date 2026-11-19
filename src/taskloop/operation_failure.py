"""The one shape every refusal and unknown of an operation takes."""

from dataclasses import dataclass
from typing import Literal

from taskloop.machine_config import ConfigRefused
from taskloop.slots import SlotView

type FailureKind = Literal["refused", "unavailable", "uncertain", "rejected", "not_applicable", "unsettled",
                          "uncommitted", "waiting", "defect"]


@dataclass(frozen=True)
class Failed:
    """Every refusal and unknown in one shape; `detail` is diagnostic only. `admitted`: this start admitted the attempt
    before its launch failed, so the tracker claim and the slot are held (re-running `tl step start` retries the launch).
    `checks`: a checks attempt's refusal (its words are guided by `step_guide.CHECKS_GUIDE` where they differ); `land`: a
    land candidate's (guided by `land_guide.LAND_GUIDE` first)."""

    kind: FailureKind
    reason: str
    detail: str = ""
    claim_leaked: bool = False
    slots: tuple[SlotView, ...] = ()
    admitted: bool = False
    checks: bool = False
    land: bool = False
    config: ConfigRefused | None = None

    @property
    def word(self) -> str:
        return f"{self.kind}:{self.reason}"
