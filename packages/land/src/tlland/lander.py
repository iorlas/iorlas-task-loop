"""The land: one commit per task, then fetch, rebase and the gate outside the land lock (land_optimistic_tries), then (one land at a time
per repo) fetch, rebase, the repo's checks again after a lost push race, the gate only when main moved under the outside gate and the
tries are used up, and the push. A red gate, a conflict or red checks are fixed outside the lock; a rejected push tries again (three
times); a network error rests until the network is back. The pushed tree is always one the gate passed on the same base."""
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tlkernel import askspecs, trustroots
from tlkernel import log as rec
from tlkernel.bead import Bead
from tlkernel.deadline import DeadlineExpired
from tlkernel.lanesliveness import LIVENESS
from tlkernel.netretry import NET_WAIT_CAP_S

from tlland import gate
from tlland.fix import FixOutside
from tlland.gate import Gate, GatePass, Problem, ProblemKind
from tlland.host import Land, Next, Phase, Placing
from tlland.lander_host import LanderHost, LandHost
from tlland.ports import Deadline
from tlland.pr_land import PrLand
from tlland.push import Landed, Outbound, Pusher
from tlland.rebase import Commit, LandRebase, Recheck
from tlland.record import Sync


class GateStep(Protocol):
    def green(self) -> bool: ...
    def passed(self) -> GatePass | None: ...
    def run(self) -> GatePass | Problem: ...


class CommitStep(Protocol):
    def run(self, bead: Bead, base_ref: str) -> bool: ...


class LandedStep(Protocol):
    def already(self, fetch: bool = ...) -> str: ...
    def found(self, sha: str) -> str: ...


class RebaseStep(Protocol):
    def run(self, fetched: int, tail: str) -> Problem | None: ...


class RecheckStep(Protocol):
    def run(self, tries: int) -> Problem | None: ...


class PushStep(Protocol):
    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next: ...


class FixStep(Protocol):
    def run(self, problem: Problem) -> None: ...


class SyncStep(Protocol):
    def run(self, sha: str) -> str: ...


class WipOut(Protocol):
    def wip_push(self, stage: int) -> None: ...


class PrStep(Protocol):
    def settled(self) -> str: ...
    def done(self) -> None: ...


@dataclass(frozen=True)
class LandParts:
    """The steps the Lander composes; each is built over its own small host (see Lander.of). `pr` is the PR land (land_mode pr),
    which is also the `push`; None in push mode."""

    gate: GateStep
    commit: CommitStep
    landed: LandedStep
    rebase: RebaseStep
    recheck: RecheckStep
    push: PushStep
    fix: FixStep
    sync: SyncStep
    out: WipOut
    pr: PrStep | None = None


class Lander:
    def __init__(self, host: LandHost, parts: LandParts, *, deadline: Deadline) -> None:
        self.e = host
        self.deadline = deadline
        self.gate = parts.gate
        self.committing = parts.commit
        self.landed = parts.landed
        self.rebasing = parts.rebase
        self.rechecking = parts.recheck
        self.pushing = parts.push
        self.fixing = parts.fix
        self.syncing = parts.sync
        self.out = parts.out
        self.pr = parts.pr

    def finish(self, bead: Bead) -> str:
        """The task's one commit, then the land. -> the landed sha, or "" (nothing changed, or a dry run)."""
        e = self.e
        why = trustroots.refusal(e.git, e.wt, e.cfg.base, e.store.show(e.bead))
        if why:
            raise e.blocked_for(why, "ASK_DECISION", spec=askspecs.open_question(why, None, "decision"))
        if e.pending_land_validation:
            raise e.blocked_for("land retry validation still needs accepted checks and review; branch kept", "FAULT_LAND")
        skipped = gate.refuse(gate.latest(e.last_run, e.latest_check.get), e)
        if skipped:
            e.log.note(f"landing with deferred checks (no such resource here, inputs unchanged): {', '.join(skipped)}")
        merged = self.pr.settled() if self.pr else ""  # a PR the owner merged since: its merge commit is the land
        if merged:
            return self.synced(merged)
        found = self.landed.already()  # the last run's push may have gone through before the network cut its answer
        if found:
            return self.synced(self.landed.found(found))
        if not e.git.dirty(e.wt) and e.git.count(e.wt, ["HEAD"], [e.cfg.base]) == 0:
            e.log.note("nothing changed")
            return ""
        if not self.committing.run(bead, e.cfg.base):
            e.log.note("nothing changed")  # (the wip commits add up to the base's own tree)
            return ""
        if e.dry:
            e.log.note("dry run: not landing")
            return ""
        e.task_branch = e.git.branch(e.wt)
        return self.synced(self.land())

    def synced(self, sha: str) -> str:
        """The land is done and the lock is let go: bd's data and the landed fact follow (see Sync)."""
        done = self.syncing.run(sha)
        if self.pr and done:
            self.pr.done()  # recorded and synced: the bead waits on no PR any more
        return done

    def lock(self) -> AbstractContextManager[Path | str]:
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        return self.e.waits.locked("land_lock", self.e.land_lock_path())

    def land(self) -> str:
        e = self.e
        st, resting = Land(), False
        while True:
            if st.iterations >= LIVENESS.land_iterations:
                raise e.blocked_for(f"land iteration cap ({LIVENESS.land_iterations}) reached; branch kept", "OWNER_PARK")
            st.iterations += 1
            if resting:  # a network failure, with the lock let go: wait for the network, then fetch and look again
                waited, back = e.worker.acts.await_net(e.worker.acts.net_up(), NET_WAIT_CAP_S)
                if not back:
                    raise e.blocked_for(f"paused: no network for the land push after {waited} s; the branch is kept, the next run lands it",
                                        "PAUSE_NETWORK")
                resting = False
            if self.optimistic(st):
                problem = self.outside(st)  # fetch, rebase and the gate without the lock
                if problem is not None:
                    if problem.kind is ProblemKind.STALE:  # main or the tree moved under the gate: no fix round, run it again
                        st.moved += 1
                    else:
                        self.fixing.run(problem)
                    continue
            with self.lock():
                sha, problem = self.tries(st)
            if sha:
                return sha
            self.count_stale(st, problem)
            if problem is None:
                resting = True
            elif problem.kind is not ProblemKind.STALE:  # stale: main moved under the gate: the lock is let go, the gate runs outside
                self.fixing.run(problem)

    def count_stale(self, st: Land, problem: Problem | None) -> None:
        """In-lock STALE answers have their own budget, even after optimistic tries are exhausted."""
        if problem is not None and problem.kind is ProblemKind.STALE:
            st.stale += 1
            if st.stale >= LIVENESS.stale_retries:
                raise self.e.blocked_for(f"in-lock STALE retry cap ({LIVENESS.stale_retries}) reached; branch kept", "OWNER_PARK")

    def optimistic(self, st: Land) -> bool:
        """The gate runs before the lock: there is a gate, tries are allowed, and no push may have gone through unseen."""
        e = self.e
        tries = e.cfg.land_optimistic_tries
        return bool(e.cfg.gate_checks) and tries > 0 and st.moved <= tries and st.phase is not Phase.NET_DOWN

    def outside(self, st: Land) -> Problem | None:
        """Without the lock: fetch, rebase, gate. -> the problem for a fix round, or None (the gate is cached for tree + base)."""
        e = self.e
        st.attempts += 1
        e.steps.begin("land", f"land (gate before the lock, try {st.attempts})", **{"try": st.attempts})
        e.newfiles.quarantine_strays()
        before, head = e.git.rev_parse(e.wt, e.cfg.base), e.git.rev_parse(e.wt, "HEAD")
        m0 = time.monotonic()
        rc, tail = e.checkout.fetch()
        m1 = time.monotonic()
        problem = self.rebasing.run(rc, tail)
        m2 = time.monotonic()
        where = Placing.NO_GATE
        if problem is None:
            where = Placing.CACHED if self.gate.green() else Placing.OUTSIDE
            got = self.gate.run()
            problem = got if isinstance(got, Problem) else None
        self.emit(st, before, head, problem, where, (m1 - m0, m2 - m1, time.monotonic() - m2))
        st.phase = Phase.STEP_OPEN if problem is None else Phase.FRESH
        return problem

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

    def tries(self, st: Land) -> tuple[str, Problem | None]:
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


def lander_over(host: LanderHost, *, deadline: Deadline) -> Lander:
    """The Lander over the engine: each step gets the host typed as that step's own Protocol."""
    out = Outbound(host)
    pr = PrLand(host) if host.cfg.land_mode == "pr" else None
    return Lander(host, LandParts(gate=Gate(host), commit=Commit(host), landed=Landed(host), rebase=LandRebase(host),
                                  recheck=Recheck(host), push=pr or Pusher(host, out), fix=FixOutside(host), sync=Sync(host, out), out=out,
                                  pr=pr), deadline=deadline)
