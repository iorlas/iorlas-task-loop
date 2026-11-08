"""The in-lock land tries and their gate passes, retry budgets and timing records."""
import time
from typing import Protocol

from tlkernel import log as rec
from tlkernel.deadline import DeadlineExpired
from tlkernel.lanesliveness import LIVENESS

from tlland.gate import GatePass, Problem, ProblemKind
from tlland.host import Land, Next, Phase, Placing
from tlland.lander_host import LandHost
from tlland.ports import Deadline


class GateStep(Protocol):
    def green(self) -> bool: ...
    def passed(self) -> GatePass | None: ...
    def run(self) -> GatePass | Problem: ...


class LandedStep(Protocol):
    def already(self, fetch: bool = ...) -> str: ...
    def found(self, sha: str) -> str: ...


class RebaseStep(Protocol):
    def run(self, fetched: int, tail: str) -> Problem | None: ...


class RecheckStep(Protocol):
    def run(self, tries: int) -> Problem | None: ...


class PushStep(Protocol):
    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next: ...


class Tries:
    def __init__(self, host: LandHost, gate: GateStep, landed: LandedStep, rebase: RebaseStep,
                 recheck: RecheckStep, push: PushStep, *, deadline: Deadline) -> None:
        self.e = host
        self.gate = gate
        self.landed = landed
        self.rebasing = rebase
        self.rechecking = recheck
        self.pushing = push
        self.deadline = deadline

    def emit(self, st: Land, before: str, head: str, problem: Problem | None, where: Placing, secs: tuple[float, float, float]) -> None:
        e = self.e
        e.log.emit(
            rec.LandTry(
                n=st.attempts,
                base_before=before[:12],
                base_after=e.git.rev_parse(e.wt, e.cfg.base)[:12],
                rebase_moved=e.git.rev_parse(e.wt, "HEAD") != head,
                failing=problem.kind.value if problem else "",
                gate=where.value,
                fetch_s=round(secs[0], 3),
                rebase_s=round(secs[1], 3),
                gate_s=round(secs[2], 3),
            )
        )

    def placing(self, st: Land) -> Placing:
        """Where the gate runs in the lock (see Placing)."""
        e = self.e
        if not e.cfg.gate_checks:
            return Placing.NO_GATE
        if self.gate.green():
            return Placing.CACHED
        if st.moved < e.cfg.land_optimistic_tries:
            st.moved += 1
            return Placing.STALE
        return Placing.INSIDE

    def run(self, st: Land) -> tuple[str, Problem | None]:
        """Inside the lock: an initial push plus at most two main-moved retries. -> (sha, None) landed; ("", problem) to fix outside the
        lock; ("", None) a network error: rest first."""
        e = self.e
        while True:
            st.attempts += 1
            if st.phase is not Phase.STEP_OPEN:
                e.steps.begin("land", f"land (try {st.attempts})", **{"try": st.attempts})
            if st.phase is Phase.STEP_OPEN:
                st.phase = Phase.FRESH
            e.newfiles.quarantine_strays()
            before, head = e.git.rev_parse(e.wt, e.cfg.base), e.git.rev_parse(e.wt, "HEAD")
            m0 = time.monotonic()
            rc, tail = e.checkout.fetch()
            m1 = time.monotonic()
            if rc == 0 and (st.pushes or st.phase is Phase.NET_DOWN):
                found = self.landed.already(fetch=False)  # an earlier push of this land may have gone through
                if found:
                    return self.landed.found(found), None
                st.phase = Phase.FRESH  # looked: not landed
            problem = self.rebasing.run(rc, tail)
            m2 = time.monotonic()
            where = self.placing(st) if problem is None else Placing.NO_GATE
            if where is Placing.STALE:
                problem = Problem(ProblemKind.STALE, "")
            if problem is None and st.pushes:
                problem = self.rechecking.run(st.pushes)
            gate_pass: GatePass | None = None
            if problem is None:
                gate_pass, problem = self.pass_for(where)
            self.emit(st, before, head, problem, Placing.NO_GATE if where is Placing.STALE else where,
                      (m1 - m0, m2 - m1, time.monotonic() - m2))
            if gate_pass is None:
                return "", problem
            got = self.pushing.push(st, gate_pass)
            if got is not Next.AGAIN:
                return self.settled(st, got)

    @staticmethod
    def settled(st: Land, got: str | Problem | Next) -> tuple[str, Problem | None]:
        """A push that did not ask for another try, as the tries' answer."""
        if isinstance(got, Problem):  # the pass went stale before the push: nothing pushed, the lock is let go
            st.moved += 1
            return "", got
        return ("", None) if isinstance(got, Next) else (got, None)

    def pass_for(self, where: Placing) -> tuple[GatePass | None, Problem | None]:
        """The pass the push will carry: the gate's own (cached or run inside the lock), or a vacuous one (no gate).
        -> (pass, None) or (None, problem)."""
        e = self.e
        if where is Placing.INSIDE:
            try:
                with self.deadline(LIVENESS.judge_s, "land judge"):
                    got = self.gate.run()
            except DeadlineExpired as err:
                if err.scope != "land judge":
                    raise
                raise e.blocked_for(f"{err}; branch kept for retry", "PAUSE_LANE") from None
            return (None, got) if isinstance(got, Problem) else (got, None)
        gate_pass = self.gate.passed()
        if gate_pass is None:  # it was green a moment ago and is not now: main or the tree moved
            return None, Problem(ProblemKind.STALE, "")
        if where is Placing.CACHED:
            e.log.note(f"gate passed outside the lock on this tree and base ({gate_pass.tree[:12]}): pushing")
        return gate_pass, None

    def count_stale(self, st: Land, problem: Problem | None) -> None:
        """In-lock STALE answers have their own budget, even after optimistic tries are exhausted."""
        if problem is not None and problem.kind is ProblemKind.STALE:
            st.stale += 1
            if st.stale >= LIVENESS.stale_retries:
                raise self.e.blocked_for(f"in-lock STALE retry cap ({LIVENESS.stale_retries}) reached; branch kept", "OWNER_PARK")
