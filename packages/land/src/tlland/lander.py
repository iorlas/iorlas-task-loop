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
from tlkernel.bead import Bead
from tlkernel.lanesliveness import LIVENESS
from tlkernel.netretry import NET_WAIT_CAP_S

from tlland import gate
from tlland.fix import FixOutside
from tlland.gate import Gate, Problem, ProblemKind
from tlland.host import Land, Phase, Placing
from tlland.lander_host import LanderHost, LandHost
from tlland.ports import Deadline
from tlland.pr_land import PrLand
from tlland.push import Landed, Outbound, Pusher
from tlland.rebase import Commit, LandRebase, Recheck
from tlland.record import Sync
from tlland.tries import GateStep, LandedStep, PushStep, RebaseStep, RecheckStep, Tries


class CommitStep(Protocol):
    def run(self, bead: Bead, base_ref: str) -> bool: ...


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
        self.inside = Tries(host, parts.gate, parts.landed, parts.rebase, parts.recheck, parts.push, deadline=deadline)

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
                sha, problem = self.inside.run(st)
            if sha:
                return sha
            self.inside.count_stale(st, problem)
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
        self.inside.emit(st, before, head, problem, where, (m1 - m0, m2 - m1, time.monotonic() - m2))
        st.phase = Phase.STEP_OPEN if problem is None else Phase.FRESH
        return problem


def lander_over(host: LanderHost, *, deadline: Deadline) -> Lander:
    """The Lander over the engine: each step gets the host typed as that step's own Protocol."""
    out = Outbound(host)
    pr = PrLand(host) if host.cfg.land_mode == "pr" else None
    return Lander(host, LandParts(gate=Gate(host), commit=Commit(host), landed=Landed(host), rebase=LandRebase(host),
                                  recheck=Recheck(host), push=pr or Pusher(host, out), fix=FixOutside(host), sync=Sync(host, out), out=out,
                                  pr=pr), deadline=deadline)
