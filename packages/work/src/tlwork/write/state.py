"""StageState: where one stage of the plan stands between its rounds: the counters a round reads and the next one changes. A round's
step answers "" (go on to the next step) or what the round came to: AGAIN, ACCEPT or REPLAN."""
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from tlkernel.checks import CheckRun
from tlkernel.ids import CheckId
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.wire import Open

AGAIN = "again"  # a round's answer: go round once more
ACCEPT = "accept"  # the stage is done
REPLAN = "replan"  # the stage cannot be done as planned


@dataclass
class RoundResult:
    """What one round came to, handed to StageLoop by value: the flow (what the round's step answers), the check run, why the stage is
    stuck, the tests the task's diff added and removed, the writes and rounds it used up, the reviews it ran, the writer's summary, family
    and thread row. A round assigns none of these on the engine; StageLoop.play applies the result once, also when the round raises."""
    flow: str = ""
    run: CheckRun | None = None
    stuck_why: str | None = None
    tests: tuple[int, int] | None = None
    rounds: int = 0
    writes: int = 0
    reviews: int = 0
    summary: str | None = None
    family: str | None = None
    last_stage: bool | None = None
    write_rows: tuple[Open, ...] = ()


class RoundStop(Exception):
    """A round raised (a question parks the bead, a check hit its wall limit, a crash): `result` is what it had come to, `cause` is the
    exception. StageLoop.play applies the result and raises the cause."""

    def __init__(self, result: RoundResult, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.result, self.cause = result, cause


@contextmanager
def carrying(out: RoundResult) -> Generator[None]:
    """Wrap a round's body: whatever it raises leaves with `out` attached."""
    try:
        yield
    except BaseException as ex:
        raise RoundStop(out, ex) from None


class WriteState:
    """What the write stage owns across the whole run (the engine's `write`). None of it is checkpointed; the trace and the closing
    records read it."""

    def __init__(self) -> None:
        self.write_rounds: list[Open] = []  # per write round: resumed, input tokens, turns, prompt chars, context k, why fresh
        self.last_summary = ""  # the last write's summary: a fresh writer is told it
        self.account_notes: list[str] = []  # steps that ran on the writer's own family, with delegate's warning
        self.strays: list[str] = []  # unaccepted untracked files moved to evidence/strays before the land gate (tl-bxk.10.24)


class StageState:
    def __init__(self, plan: PlanData, i: int, state: RoundState | None) -> None:
        self.i, self.state = i, state or RoundState()
        self.stages = len(plan["stages"])
        self.st = plan["stages"][i]
        self.last = i == self.stages - 1
        self.fix = self.state.get("fix")
        self.sk = 1000 + (self.state.get("fix_n") or 0) if self.fix else i  # the stage's place in a call's key (CallState)
        self.name = self.state.get("name") or f"stage {i + 1}/{self.stages}"
        self.feedback: str = self.state.get("feedback", "")
        self.rounds: int = self.state.get("rounds", 0)
        self.n: int = self.state.get("n", 0)
        self.run_checks: list[CheckId] = []
        self.request_feedback = ""
        self.red = 0
        self.prepare_retried = False
        self.failed_cmds: list[str] | None = self.state.get("failed")  # the commands the last engine run found red (None: none ran red yet)
        self.shots_fixed = False  # a visual write without shots or a reason is sent back once, at no cost to the rounds (tl-tno)
        self.show_fixed = False  # a show item without its artifacts is sent back once, at no cost to the rounds (tl-jvpm.25)
        self.red_now: set[str] = set()  # the commands the last round found red
        self.acc_first = False  # the last round ran acceptance first
        self.acc_only = False  # the last round's red checks were all acceptance ones (tl-bxk.13.14)
        self.meta: dict[str, Any] = ({"fix": self.state.get("fix_n"), "fixes": self.state.get("fix_of")} if self.fix else
                                     {"stage": i + 1, "stages": self.stages})
        self.w: dict[str, Any] = {}  # this round's write answer
        self.wfam = ""
        self.wrote_unchecked: list[dict[str, Any]] = []
        self.run: Any = None  # this round's check run
