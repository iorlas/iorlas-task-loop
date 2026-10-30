"""The land: one commit per task, then fetch, rebase and the gate outside the land lock (land_optimistic_tries), then (one land at a time
per repo) fetch, rebase, the repo's checks again after a lost push race, the gate only when main moved under the outside gate and the
tries are used up, and the push. A red gate, a conflict or red checks are fixed outside the lock; a rejected push tries again (three
times); a network error rests until the network is back. The pushed tree is always one the gate passed on the same base."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taskloop.app.land import verified
from taskloop.app.land.commit import Commit
from taskloop.app.land.fix_outside import FixOutside
from taskloop.app.land.gate import Gate, GatePass, Problem, ProblemKind
from taskloop.app.land.land_rebase import LandRebase
from taskloop.app.land.landed import Landed
from taskloop.app.land.lander_host import LanderHost, LandHost
from taskloop.app.land.outbound import Outbound
from taskloop.app.land.push import Pusher
from taskloop.app.land.recheck import Recheck
from taskloop.app.land.state import Land, Next, Phase, Placing
from taskloop.app.land.sync import Sync
from taskloop.contracts import log as rec
from taskloop.contracts.bead import Bead
from taskloop.domain.lanes import policy as lp


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


@dataclass(frozen=True)
class LandParts:
    """The steps the Lander composes; each is built over its own small host (see Lander.of)."""

    gate: GateStep
    commit: CommitStep
    landed: LandedStep
    rebase: RebaseStep
    recheck: RecheckStep
    push: PushStep
    fix: FixStep
    sync: SyncStep
    out: WipOut


class Lander:
    def __init__(self, host: LandHost, parts: LandParts) -> None:
        self.e = host
        self.gate = parts.gate
        self.committing = parts.commit
        self.landed = parts.landed
        self.rebasing = parts.rebase
        self.rechecking = parts.recheck
        self.pushing = parts.push
        self.fixing = parts.fix
        self.syncing = parts.sync
        self.out = parts.out

    def finish(self, bead: Bead) -> str:
        """The task's one commit, then the land. -> the landed sha, or "" (nothing changed, or a dry run)."""
        e = self.e
        if e.pending_land_validation:
            raise e.blocked_for("land retry validation still needs accepted checks and review; branch kept", "FAULT_LAND")
        verified.refuse(verified.latest(e.last_run, lambda: e.stores.check_run(e.run_dir.name, None).get()), e)
        found = self.landed.already()  # the last run's push may have gone through before the network cut its answer
        if found:
            return self.synced(self.landed.found(found))
        if not e.git("status", "--porcelain") and e.git("rev-list", "--count", f"{e.cfg.base}..HEAD") in ("", "0"):
            e.log.note("nothing changed")
            return ""
        if not self.committing.run(bead, e.cfg.base):
            e.log.note("nothing changed")  # (the wip commits add up to the base's own tree)
            return ""
        if e.dry:
            e.log.note("dry run: not landing")
            return ""
        e.task_branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        return self.synced(self.land())

    def synced(self, sha: str) -> str:
        """The land is done and the lock is let go: bd's data and the landed fact follow (see Sync)."""
        return self.syncing.run(sha)

    def lock(self) -> AbstractContextManager[Path | str]:
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        return self.e.waits.locked("land_lock", self.e.land_lock_path())

    def land(self) -> str:
        e = self.e
        st, resting = Land(), False
        while True:
            if resting:  # a network failure, with the lock let go: wait for the network, then fetch and look again
                waited, back = e.worker.acts.await_net(e.worker.acts.net_up(), lp.KNOBS["net_wait_cap_s"])
                if not back:
                    raise e.blocked_for(f"paused: no network for the land push after {waited} s; the branch is kept, the next run lands it",
                                        "PAUSE_NETWORK")
                resting = False
            if self.optimistic(st):
                problem = self.outside(st)  # fetch, rebase and the gate without the lock
                if problem is not None:
                    self.fixing.run(problem)
                    continue
            with self.lock():
                sha, problem = self.tries(st)
            if sha:
                return sha
            if problem is None:
                resting = True
            elif problem.kind is not ProblemKind.STALE:  # stale: main moved under the gate: the lock is let go, the gate runs outside
                self.fixing.run(problem)

    def optimistic(self, st: Land) -> bool:
        """The gate runs before the lock: there is a gate, tries are allowed, and no push may have gone through unseen."""
        e = self.e
        tries = e.cfg.land_optimistic_tries
        return bool(e.cfg.gate_checks) and tries > 0 and st.moved <= tries and st.phase is not Phase.NET_DOWN

    def outside(self, st: Land) -> Problem | None:
        """Without the lock: fetch, rebase, gate. -> the problem for a fix round, or None (the gate is cached for tree + base)."""
        e = self.e
        e.steps.begin("land", f"land (gate before the lock, try {st.pushes + 1})", **{"try": st.pushes + 1})
        e.newfiles.quarantine_strays()
        before, head = e.git("rev-parse", e.cfg.base), e.git("rev-parse", "HEAD")
        rc, tail = e.checkout.fetch()
        problem = self.rebasing.run(rc, tail)
        where = Placing.NO_GATE
        if problem is None:
            where = Placing.CACHED if self.gate.green() else Placing.OUTSIDE
            got = self.gate.run()
            problem = got if isinstance(got, Problem) else None
        self.emit(st, before, head, problem, where)
        st.phase = Phase.STEP_OPEN if problem is None else Phase.FRESH
        return problem

    def emit(self, st: Land, before: str, head: str, problem: Problem | None, where: Placing) -> None:
        e = self.e
        e.log.emit(rec.LandTry(n=st.pushes + 1, base_before=before[:12], base_after=e.git("rev-parse", e.cfg.base)[:12],
                               rebase_moved=e.git("rev-parse", "HEAD") != head, failing=problem.kind.value if problem else "",
                               gate=where.value))

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
            if st.phase is not Phase.STEP_OPEN:
                e.steps.begin("land", f"land (try {st.pushes + 1})", **{"try": st.pushes + 1})
            if st.phase is Phase.STEP_OPEN:
                st.phase = Phase.FRESH
            e.newfiles.quarantine_strays()
            before, head = e.git("rev-parse", e.cfg.base), e.git("rev-parse", "HEAD")
            rc, tail = e.checkout.fetch()
            if rc == 0 and (st.pushes or st.phase is Phase.NET_DOWN):
                found = self.landed.already(fetch=False)  # an earlier push of this land may have gone through
                if found:
                    return self.landed.found(found), None
                st.phase = Phase.FRESH  # looked: not landed
            problem = self.rebasing.run(rc, tail)
            where = self.placing(st) if problem is None else Placing.NO_GATE
            if where is Placing.STALE:
                problem = Problem(ProblemKind.STALE, "")
            if problem is None and st.pushes:
                problem = self.rechecking.run(st.pushes)
            gate_pass: GatePass | None = None
            if problem is None:
                gate_pass, problem = self.pass_for(where)
            self.emit(st, before, head, problem, Placing.NO_GATE if where is Placing.STALE else where)
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
            got = self.gate.run()
            return (None, got) if isinstance(got, Problem) else (got, None)
        gate_pass = self.gate.passed()
        if gate_pass is None:  # it was green a moment ago and is not now: main or the tree moved
            return None, Problem(ProblemKind.STALE, "")
        if where is Placing.CACHED:
            e.log.note(f"gate passed outside the lock on this tree and base ({gate_pass.tree[:12]}): pushing")
        return gate_pass, None


def lander_over(host: LanderHost) -> Lander:
    """The Lander over the engine: each step gets the host typed as that step's own Protocol."""
    out = Outbound(host)
    return Lander(host, LandParts(gate=Gate(host), commit=Commit(host), landed=Landed(host), rebase=LandRebase(host),
                                  recheck=Recheck(host), push=Pusher(host, out), fix=FixOutside(host), sync=Sync(host, out), out=out))
