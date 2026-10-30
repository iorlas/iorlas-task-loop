"""The land: one commit per task, then fetch, rebase and the gate outside the land lock (land_optimistic_tries), then (one land at a time
per repo) fetch, rebase, the repo's checks again after a lost push race, the gate only when main moved under the outside gate and the
tries are used up, and the push. A red gate, a conflict or red checks are fixed outside the lock; a rejected push tries again (three
times); a network error rests until the network is back. The pushed tree is always one the gate passed on the same base."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.land import verified
from taskloop.app.land.gate import Gate, GatePass, Problem, ProblemKind
from taskloop.app.land.lander_host import LanderHost
from taskloop.app.land.outbound import Outbound, land_argv, pin_head
from taskloop.contracts import fence
from taskloop.contracts import log as rec
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import CheckRun
from taskloop.domain.land.matchers import Push
from taskloop.domain.lanes import policy as lp

PUSH_UP_FAILS = 3  # network errors on the push while the probe says the network is up: not the network's to cure (a proxy, DNS)
PUSH_TRIES = 3  # a push rejected because main moved is tried again this often

class Phase(Enum):
    """Where the land stands between its tries (one state, not two flags)."""

    FRESH = "fresh"
    STEP_OPEN = "step open"  # the outside gate's land step is still open: the lock's first try goes on in it
    NET_DOWN = "net down"  # the last push died of the network: look again before pushing


class Placing(Enum):
    """Where the gate runs for the push in the lock."""

    NO_GATE = ""
    CACHED = "cached"  # it passed on this tree and base
    STALE = "stale"  # main moved under the outside gate: let the lock go, gate outside again
    INSIDE = "inside"  # the tries are used up: gate here, as a busy main must not starve a bead
    OUTSIDE = "outside"


class Next(Enum):
    """What a push that did not land asks of the land."""

    AGAIN = "again"  # rejected: main moved, try again in this lock
    REST = "rest"  # a network error: rest first


@dataclass
class Land:
    """What survives from one try of the land to the next."""

    pushes: int = 0  # rejected pushes so far
    flaky: int = 0  # network errors on the push while the network looked up
    phase: Phase = Phase.FRESH
    moved: int = 0  # times the lock was let go because main moved under the gate: the gate runs outside again (land_optimistic_tries)


class Lander:
    def __init__(self, host: LanderHost) -> None:
        self.e = host
        self.gate = Gate(host)
        self.out = Outbound(host)

    def finish(self, bead: Bead) -> str:
        """The task's one commit, then the land. -> the landed sha, or "" (nothing changed, or a dry run)."""
        e = self.e
        if e.pending_land_validation:
            raise e.blocked_for("land retry validation still needs accepted checks and review; branch kept", "FAULT_LAND")
        self.refuse_unverified(verified.latest(e.last_run, lambda: e.stores.check_run(e.run_dir.name, None).read()))
        found = self.already()  # the last run's push may have gone through before the network cut its answer
        if found:
            return self.synced(self.found(found))
        if not e.git("status", "--porcelain") and e.git("rev-list", "--count", f"{e.cfg.base}..HEAD") in ("", "0"):
            e.log.note("nothing changed")
            return ""
        if not self.commit(bead):
            e.log.note("nothing changed")  # (the wip commits add up to the base's own tree)
            return ""
        if e.dry:
            e.log.note("dry run: not landing")
            return ""
        e.task_branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        return self.synced(self.land())

    def refuse_unverified(self, run: CheckRun | None) -> None:
        """A required check that could not verify is no pass: nothing is committed or pushed (verified.deferred is tl-7k8.5's hook)."""
        why = verified.refusal(run) if run else ""
        if why:
            raise self.e.blocked_for(why, "FAULT_LAND")

    def synced(self, sha: str) -> str:
        """The land is done and the lock is let go: bd's data follows it (a failure there blocks the bead)."""
        if sha and not self.e.dry:
            self.out.bd_sync(sha)
        return sha

    def commit(self, bead: Bead) -> bool:
        """One commit per task, titled after the bead: earlier runs' wip commits are folded in. -> False: they add up to nothing."""
        e = self.e
        base = e.git("merge-base", "HEAD", e.cfg.base)
        if base:
            e.sh(["git", "reset", "-q", "--soft", base], check=True, pin=True)
        e.pictures.copy_looks()
        e.checkout.stage_all(check=True)
        e.newfiles.quarantine_strays()
        if base and not e.sh(["git", "diff", "--cached", "--quiet"], pin=True)[0]:
            return False
        rc, tail = e.sh(["git", "commit", "-q", "-m", f"{bead.title[:72]} ({e.bead})"], pin=True)
        if rc:
            raise e.blocked_for("failed: commit refused (hooks)\n" + tail, "FAULT_LAND")
        return True

    def already(self, fetch: bool = True) -> str:
        """tl-7y6.2.13: a push that died of the network after origin took it. The task branch's tip is the land commit (titled
        `... (<bead>)`) and it is on the base: it landed, and nothing is pushed twice. -> its sha, or ''."""
        e = self.e
        if e.dry or (fetch and e.checkout.fetch()[0]):
            return ""
        tip = e.git("rev-parse", "--verify", "-q", "HEAD")
        if not tip or not e.git("log", "-1", "--format=%s").endswith(f"({e.bead})"):
            return ""
        return tip if e.sh(["git", "merge-base", "--is-ancestor", tip, e.cfg.base], pin=True)[0] == 0 else ""

    def found(self, sha: str) -> str:
        e = self.e
        e.landed_sha = sha
        e.record_land(sha)
        e.steps.outcome("landed", sha[:12])
        e.warn(f"the push had already gone through ({sha[:12]} is on {e.cfg.base}): not pushed again")
        return sha

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
                    self.fix_outside_lock(problem)
                    continue
            with self.lock():
                sha, problem = self.tries(st)
            if sha:
                return sha
            if problem is None:
                resting = True
            elif problem.kind is not ProblemKind.STALE:  # stale: main moved under the gate: the lock is let go, the gate runs outside
                self.fix_outside_lock(problem)

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
        problem = self.rebase(rc, tail)
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
                found = self.already(fetch=False)  # an earlier push of this land may have gone through
                if found:
                    return self.found(found), None
                st.phase = Phase.FRESH  # looked: not landed
            problem = self.rebase(rc, tail)
            where = self.placing(st) if problem is None else Placing.NO_GATE
            if where is Placing.STALE:
                problem = Problem(ProblemKind.STALE, "")
            if problem is None and st.pushes:
                problem = self.recheck(st)
            gate_pass: GatePass | None = None
            if problem is None:
                gate_pass, problem = self.pass_for(where)
            self.emit(st, before, head, problem, Placing.NO_GATE if where is Placing.STALE else where)
            if gate_pass is None:
                return "", problem
            got = self.push(st, gate_pass)
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

    def rebase(self, fetched: int, tail: str) -> Problem | None:
        e = self.e
        rc = fetched
        if rc == 0:
            rc, tail = e.sh(["git", "rebase", "-q", e.cfg.base], pin=True)
        if not rc:
            return None
        unmerged = e.git("diff", "--name-only", "--diff-filter=U")
        if not unmerged:
            e.sh(["git", "rebase", "--abort"], pin=True)
            raise e.blocked_for(f"failed: fetch or rebase onto {e.cfg.base} failed; branch kept\n{tail}", "FAULT_LAND")
        e.steps.outcome("conflict", ", ".join(unmerged.split()))
        return Problem(ProblemKind.CONFLICT, "Conflicted files: {}\n{}".format(", ".join(unmerged.split()), tail))

    def recheck(self, st: Land) -> Problem | None:
        """After a lost push race: revalidate the rebased inputs. Repo checks reuse their input cache; stage/case checks stay conservative
        because they can depend on state outside the tracked tree."""
        e = self.e
        stages = (e.plan_data or {}).get("stages") or []
        checks = list(dict.fromkeys([*(c for s in stages for c in s["checks"]), *e.cases.case_checks()]))
        # A stop during checks or just after they return must resume through acceptance: save that barrier first
        self.park("land retry checks require successful checks and review before landing", "land-verify-red")
        results = e.stage_checks.stoppable({"checks": checks, "files": []}, "land retry")
        self.refuse_unverified(results)
        bad = results.failed
        problem = Problem(ProblemKind.VERIFY, check_evidence.failure_brief(bad, e.run_dir)) if bad else None
        self.park(problem.text if problem else "", "land-verify-red" if bad else "land")
        e.steps.begin("land", f"land (try {st.pushes + 1})", **{"try": st.pushes + 1})
        return problem

    def park(self, pending: str, step: str) -> None:
        """Save the barrier with SIGTERM deferred; a stop that came meanwhile ends the run after the save."""
        e = self.e
        with e.stop_deferred() as stop:
            e.pending_land_validation = pending
            e.checkpoints.save(stage=len((e.plan_data or {}).get("stages") or []), step=step)
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)", "PAUSE_KILLED")

    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next:
        """-> the sha landed; Next.AGAIN rejected, try again; Next.REST a network error, rest first; a stale Problem when the tree or the
        base is no longer the one the pass is for (nothing is pushed). Anything else raises."""
        e = self.e
        tree, base = e.git("rev-parse", "HEAD^{tree}"), e.git("rev-parse", e.cfg.base)
        if (tree, base) != (gate_pass.tree, gate_pass.base):
            now = f"{tree[:12]} on {base[:12]}"
            return Problem(ProblemKind.STALE, f"the gate passed tree {gate_pass.tree[:12]} on {gate_pass.base[:12]}; now {now}")
        fence.check(e.store, e.claim)  # a run whose bead or slot was taken again pushes nothing (Fenced; RunOnce closes nothing)
        with e.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
            lrc, ltail = self.out.lfs_push()  # the pushed ref's LFS objects first: the push must not point at objects origin lacks
            sha = e.git("rev-parse", "HEAD")  # the commit pushed, named in the refspec
            rc, tail = e.sh(land_argv(pin_head(e.cfg.land, sha)), pin=True) if lrc == 0 else (lrc, ltail)  # no repo hook runs: --no-verify
            if rc != 0:
                sha = ""
            else:
                e.landed_sha = sha
                e.record_land(sha)
        if rc == 0:
            e.steps.outcome("landed", sha[:12])
            if stop:
                e.warn("a stop came during the land: landed first, closing now")
            return sha
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)", "PAUSE_KILLED")
        if lrc or not Push.rejected(tail):
            self.not_rejected(st, tail, "git lfs push failed" if lrc else "land failed")
            return Next.REST
        st.pushes += 1
        e.steps.outcome("rejected", "main moved")
        if st.pushes >= PUSH_TRIES:
            raise e.blocked_for("land rejected 3 times: main moves too fast", "FAULT_LAND")
        e.warn(f"push rejected (main moved), try {st.pushes + 1} of {PUSH_TRIES}")
        e.steps.move("land", "push_race", f"push rejected (main moved): try {st.pushes + 1} of {PUSH_TRIES}")
        return Next.AGAIN

    def not_rejected(self, st: Land, tail: str, what: str = "land failed") -> None:
        """A push that failed for another reason: a network error rests, anything else is a fault."""
        e = self.e
        if not Push.transient(tail):
            raise e.blocked_for(what + "\n" + tail, "FAULT_LAND")
        if e.worker.acts.net_up() is not False:  # the probe cannot see the fault: counted, a proxy or DNS looks like this
            st.flaky += 1
        if st.flaky >= PUSH_UP_FAILS:
            raise e.blocked_for(f"paused: the land push failed {st.flaky} times with a network error while the network looks up; "
                                f"the branch is kept and the next run lands it again: {tail.strip()[-200:]}", "PAUSE_NETWORK")
        st.phase = Phase.NET_DOWN
        e.warn(f"the push failed with a network error, trying again when the network is back: {tail.strip()[-160:]}")
        e.steps.move("land", "push_network", "network error on the push; the land looks again after the network is back")

    def fix_outside_lock(self, problem: Problem) -> None:
        """A red check/gate or a conflict is fixed outside the land lock, then the land tries again."""
        e = self.e
        if e.fixes < e.cfg.max_fix_rounds:
            cause = {ProblemKind.GATE: "gate_red", ProblemKind.VERIFY: "checks_red", ProblemKind.CONFLICT: "conflict"}[problem.kind]
            first = problem.text.strip().splitlines() or [""]
            red = f"gate red on the rebased tree: {(problem.named or first[-1])[:200]}"
            e.steps.move("fix", cause, red if problem.kind is ProblemKind.GATE else problem.text.splitlines()[0])
        fixed = e.fixer.fix(problem.kind, problem.text)
        stages = len((e.plan_data or {}).get("stages") or [])
        if problem.kind is ProblemKind.VERIFY and fixed != "accept":
            e.pending_land_validation += "\n" + e.stuck_why
            e.checkpoints.save(stage=stages, step="land-verify-red")
            raise e.blocked_for("land retry validation fix did not pass its checks and review; branch kept", "FAULT_LAND")
        if problem.kind is ProblemKind.VERIFY:
            e.pending_land_validation = ""
            e.checkpoints.save(stage=stages, step="land")
            if e.git("status", "--porcelain"):  # unlike verification before finish(), a retry check's fix follows the task commit
                e.checkout.stage_all(check=True)
                e.sh(["git", "commit", "-q", "--no-verify", "--amend", "--no-edit"], check=True, pin=True)

