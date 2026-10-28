"""StageLoop: one stage of the plan. Write, then the engine's checks, then review, round after round, until the review is clean
(the stage is accepted) or the rounds are used up (the stage asks for a re-plan). A red check goes straight back to the writer: it never
reaches the reviewer. The writer's or the reviewer's question is the owner's. The rounds themselves are WriteRound, CheckRound and
ReviewRound; the host (the engine) lends the run's state."""
from typing import Any

from taskloop.app.write.check_round import CheckRound
from taskloop.app.write.review_round import ReviewRound
from taskloop.app.write.state import AGAIN, StageState
from taskloop.app.write.write_round import WriteRound


class StageLoop:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.writing = WriteRound(host)
        self.checking = CheckRound(host)
        self.reviewing = ReviewRound(host)

    def run(self, plan: dict[str, Any], i: int, state: dict[str, Any] | None = None) -> str:
        """-> "accept" or "replan" (or a Blocked stop). `state`: a resumed stage's counters, or a fix round's."""
        s = self.begin(plan, i, state)
        while True:
            flow = self.round(s)
            if flow != AGAIN:
                return flow

    def begin(self, plan: dict[str, Any], i: int, state: dict[str, Any] | None) -> StageState:
        e = self.e
        s = StageState(plan, i, state)
        e.at_stage = s.sk
        if not s.state or s.fix:  # a resumed stage keeps the checkpoint's start; the first stage starts at the task's base
            e.stage_tree = e.checkout.tree_hash() if (i or s.fix or e.amended) else ""
        if not s.state:  # a resumed stage keeps its render rounds (the checkpoint's)
            e.look_done, e.look_prev = 0, list[Any]()
        return s

    def round(self, s: StageState) -> str:
        """One write, its checks and its review. -> AGAIN, or what the stage came to."""
        e = self.e
        if not s.fix:  # a fix runs at land: its checkpoint stays at land, and a resume lands again
            e.checkpoints.save(stage=s.i, rounds=s.rounds, n=s.n, feedback=s.feedback, step="write")
            e.reload.safe_point("write")  # the round's write, checks and review run on the code that is installed now
        s.n += 1
        e.stats["writes"] += 1
        if s.n >= 2:
            e.warn(f"{s.name}: write {s.n} (round {s.rounds + 1})")
        return self.writing.run(s) or self.checking.run(s) or self.reviewing.run(s)
