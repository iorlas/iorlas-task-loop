"""StageState: where one stage of the plan stands between its rounds: the counters a round reads and the next one changes. A round's
step answers "" (go on to the next step) or what the round came to: AGAIN, ACCEPT or REPLAN."""
from typing import Any

AGAIN = "again"  # a round's answer: go round once more
ACCEPT = "accept"  # the stage is done
REPLAN = "replan"  # the stage cannot be done as planned


class StageState:
    def __init__(self, plan: dict[str, Any], i: int, state: dict[str, Any] | None) -> None:
        self.i, self.state = i, state or {}
        self.stages = len(plan["stages"])
        self.st: dict[str, Any] = plan["stages"][i]
        self.last = i == self.stages - 1
        self.fix = self.state.get("fix")
        self.sk = 1000 + int(self.state.get("fix_n") or 0) if self.fix else i  # the stage's place in a call's key (CallState)
        self.name = self.state.get("name") or f"stage {i + 1}/{self.stages}"
        self.feedback: str = self.state.get("feedback", "")
        self.rounds: int = self.state.get("rounds", 0)
        self.n: int = self.state.get("n", 0)
        self.red = 0
        self.failed_cmds: list[str] | None = self.state.get("failed")  # the commands the last engine run found red (None: none ran red yet)
        self.shots_fixed = False  # a visual write without shots or a reason is sent back once, at no cost to the rounds (tl-tno)
        self.red_now: set[str] = set()  # the commands the last round found red
        self.acc_first = False  # the last round ran acceptance first
        self.acc_only = False  # the last round's red checks were all acceptance ones (tl-bxk.13.14)
        self.meta: dict[str, Any] = ({"fix": self.state.get("fix_n"), "fixes": self.state.get("fix_of")} if self.fix else
                                     {"stage": i + 1, "stages": self.stages})
        self.w: dict[str, Any] = {}  # this round's write answer
        self.wfam = ""
        self.wrote_unchecked: list[dict[str, Any]] = []
        self.run: Any = None  # this round's check run
