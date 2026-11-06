"""StageLoop: one stage of the plan. Write, then the engine's checks, then review, round after round, until the review is clean
(the stage is accepted) or the rounds are used up (the stage asks for a re-plan). A red check goes straight back to the writer: it never
reaches the reviewer. The writer's or the reviewer's question is the owner's. The rounds themselves are WriteRound, CheckRound and
ReviewRound; the host (the engine) lends the run's state."""
from typing import Any

from taskloop.app.write.check_round import CheckRound
from taskloop.app.write.prepare import PREPARED, Prepare
from taskloop.app.write.review_round import ReviewRound
from taskloop.app.write.state import AGAIN, RoundOut, StageState
from taskloop.app.write.write_round import WriteRound
from taskloop.contracts.plancheck import PlanData, RoundState


class StageLoop:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.writing = WriteRound(host)
        self.checking = CheckRound(host)
        self.reviewing = ReviewRound(host)

    def run(self, plan: PlanData, i: int, state: RoundState | None = None) -> str:
        """-> "accept" or "replan" (or a Blocked stop). `state`: a resumed stage's counters, or a fix round's."""
        s = self.begin(plan, i, state)
        while True:
            flow = self.round(s)
            if flow != AGAIN:
                return flow

    def begin(self, plan: PlanData, i: int, state: RoundState | None) -> StageState:
        e = self.e
        s = StageState(plan, i, state)
        e.at_stage = s.sk
        if not s.state or s.fix:  # a resumed stage keeps the checkpoint's start; the first stage starts at the task's base
            e.stage_tree = e.checkout.tree_hash() if (i or s.fix or e.amended) else ""
        if not s.state:  # a resumed stage keeps its render rounds (the checkpoint's)
            e.look.done = 0
        return s

    def round(self, s: StageState) -> str:
        """One write, its checks and its review. -> AGAIN, or what the stage came to."""
        e = self.e
        if not s.fix:  # a fix runs at land: its checkpoint stays at land, and a resume lands again
            e.checkpoints.save(stage=s.i, rounds=s.rounds, n=s.n, feedback=s.feedback, step="write")
            e.reload.safe_point("write")  # the round's write, checks and review run on the code that is installed now
        Prepare(e).run()
        s.n += 1
        e.stats["writes"] += 1
        if s.n >= 2:
            e.warn(f"{s.name}: write {s.n} (round {s.rounds + 1})")
        s.prepare_retried = False
        while True:
            flow = self.write(s) or self.check(s)
            if flow != PREPARED:
                return flow or self.reviewing.run(s)

    def write(self, s: StageState, *, look: bool = True) -> str:
        try:
            return self.writing.run(s, look=look)
        finally:  # a question parks the bead by raising: the closer still reads what the round left
            self.hand_on(s)

    def check(self, s: StageState) -> str:
        try:
            return self.checking.run(s)
        finally:  # a stuck check parks the bead by raising: the closer still reads the run and why
            self.hand_on(s)

    def hand_on(self, s: StageState) -> None:
        """Apply what the rounds left in `s.out` to the engine, then clear it."""
        e, out, s.out = self.e, s.out, RoundOut()
        if out.run is not None:
            e.last_run = out.run
        if out.tests is not None:
            e.stats["tests_added"], e.stats["tests_removed"] = out.tests
        if out.stuck_why is not None:
            e.stuck_why = out.stuck_why
        if out.summary is not None:
            e.last_summary = out.summary
        e.stats["rounds"] += out.rounds
        e.stats["writes"] += out.writes
