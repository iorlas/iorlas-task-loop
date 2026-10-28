"""The land: one commit per task, then (one land at a time per repo) fetch, rebase, the repo's checks again after a lost push race, the
gate, and the push. A red gate, a conflict or red checks are fixed outside the lock; a rejected push tries again (three times); a network
error rests until the network is back."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.land.gate import Gate, Problem
from taskloop.contracts import log as rec
from taskloop.domain.land.matchers import Push
from taskloop.domain.lanes import policy as lp

PUSH_UP_FAILS = 3  # network errors on the push while the probe says the network is up: not the network's to cure (a proxy, DNS)
PUSH_TRIES = 3  # a push rejected because main moved is tried again this often

@dataclass
class Land:
    """What survives from one try of the land to the next."""

    pushes: int = 0  # rejected pushes so far
    flaky: int = 0  # network errors on the push while the network looked up
    net_failed: bool = False  # the last push died of the network: look again before pushing


class Lander:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.gate = Gate(host)

    def finish(self, bead: Any) -> str:
        """The task's one commit, then the land. -> the landed sha, or "" (nothing changed, or a dry run)."""
        e = self.e
        if e.pending_land_validation:
            raise e.blocked_for("land retry validation still needs accepted checks and review; branch kept", "FAULT_LAND")
        found = self.already()  # the last run's push may have gone through before the network cut its answer
        if found:
            return self.found(found)
        if not e.git("status", "--porcelain") and e.git("rev-list", "--count", f"{e.cfg.base}..HEAD") in ("", "0"):
            e.log.note("nothing changed")
            return ""
        self.commit(bead)
        if e.dry:
            e.log.note("dry run: not landing")
            return ""
        e.task_branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        return self.land()

    def commit(self, bead: Any) -> None:
        """One commit per task, titled after the bead: earlier runs' wip commits are folded in."""
        e = self.e
        base = e.git("merge-base", "HEAD", e.cfg.base)
        if base:
            e.sh(["git", "reset", "-q", "--soft", base], check=True, pin=True)
        e.pictures.copy_looks()
        e.checkout.stage_all(check=True)
        e.newfiles.quarantine_strays()
        rc, tail = e.sh(["git", "commit", "-q", "-m", f"{bead.title[:72]} ({e.bead})"], pin=True)
        if rc:
            raise e.blocked_for("failed: commit refused (hooks)\n" + tail, "FAULT_LAND")

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

    def lock(self) -> AbstractContextManager[Any]:
        """One land at a time per repo, across slots and sessions: an flock the OS drops when the process dies."""
        return self.e.locked("land_lock", self.e.land_lock_path())

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
            with self.lock():
                sha, problem = self.tries(st)
            if sha:
                return sha
            if problem is None:
                resting = True
                continue
            self.fix_outside_lock(problem)

    def tries(self, st: Land) -> tuple[str, Problem | None]:
        """Inside the lock: an initial push plus at most two main-moved retries. -> (sha, None) landed; ("", problem) to fix outside the
        lock; ("", None) a network error: rest first."""
        e = self.e
        while True:
            e.steps.begin("land", f"land (try {st.pushes + 1})", **{"try": st.pushes + 1})
            e.newfiles.quarantine_strays()
            before, head = e.git("rev-parse", e.cfg.base), e.git("rev-parse", "HEAD")
            rc, tail = e.checkout.fetch()
            if rc == 0 and (st.pushes or st.net_failed):
                found = self.already(fetch=False)  # an earlier push of this land may have gone through
                if found:
                    return self.found(found), None
            problem = self.rebase(rc, tail)
            if problem is None and st.pushes:
                problem = self.recheck(st)
            if problem is None and e.cfg.gate:
                problem = self.gate.run()
            e.log.emit(rec.LandTry(n=st.pushes + 1, base_before=before[:12], base_after=e.git("rev-parse", e.cfg.base)[:12],
                                   rebase_moved=e.git("rev-parse", "HEAD") != head, failing=problem.kind if problem else ""))
            if problem is not None:
                return "", problem
            sha, again = self.push(st)
            if sha or not again:
                return sha, None

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
        return Problem("conflict", "Conflicted files: {}\n{}".format(", ".join(unmerged.split()), tail))

    def recheck(self, st: Land) -> Problem | None:
        """After a lost push race: revalidate the rebased inputs. Repo checks reuse their input cache; stage/case checks stay conservative
        because they can depend on state outside the tracked tree."""
        e = self.e
        stages = (e.plan_data or {}).get("stages") or []
        checks = list(dict.fromkeys([c for s in stages for c in s["checks"]] + e.case_checks()))
        # A stop during checks or just after they return must resume through acceptance: save that barrier first
        self.park("land retry checks require successful checks and review before landing", "land-verify-red")
        results = e.stoppable_checks({"checks": checks, "files": []}, "land retry")
        bad = results.failed
        problem = Problem("verify", check_evidence.failure_brief(bad, e.run_dir)) if bad else None
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

    def push(self, st: Land) -> tuple[str, bool]:
        """-> (sha, _) landed; ("", True) rejected, try again; ("", False) a network error, rest first. Anything else raises."""
        e = self.e
        with e.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
            gated = e.git("rev-parse", "HEAD^{tree}")  # a pre-push hook may skip a gate this exact tree passed
            rc, tail = e.sh(e.cfg.land, pin=True, env={"TASK_LOOP_GATED_TREE": gated, "TL_GATE_PASSED": gated} if e.cfg.gate else None)
            sha = ""
            if rc == 0:
                e.landed_sha = sha = e.git("rev-parse", "HEAD")
                e.record_land(sha)
        if rc == 0:
            e.steps.outcome("landed", sha[:12])
            if stop:
                e.warn("a stop came during the land: landed first, closing now")
            return sha, False
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)", "PAUSE_KILLED")
        if not Push.rejected(tail):
            return "", self.not_rejected(st, tail)
        st.pushes += 1
        e.steps.outcome("rejected", "main moved")
        if st.pushes >= PUSH_TRIES:
            raise e.blocked_for("land rejected 3 times: main moves too fast", "FAULT_LAND")
        e.warn(f"push rejected (main moved), try {st.pushes + 1} of {PUSH_TRIES}")
        e.steps.move("land", "push_race", f"push rejected (main moved): try {st.pushes + 1} of {PUSH_TRIES}")
        return "", True

    def not_rejected(self, st: Land, tail: str) -> bool:
        """A push that failed for another reason: a network error rests (-> False), anything else is a fault."""
        e = self.e
        if not Push.transient(tail):
            raise e.blocked_for("land failed\n" + tail, "FAULT_LAND")
        if e.worker.acts.net_up() is not False:  # the probe cannot see the fault: counted, a proxy or DNS looks like this
            st.flaky += 1
        if st.flaky >= PUSH_UP_FAILS:
            raise e.blocked_for(f"paused: the land push failed {st.flaky} times with a network error while the network looks up; "
                                f"the branch is kept and the next run lands it again: {tail.strip()[-200:]}", "PAUSE_NETWORK")
        st.net_failed = True
        e.warn(f"the push failed with a network error, trying again when the network is back: {tail.strip()[-160:]}")
        e.steps.move("land", "push_network", "network error on the push; the land looks again after the network is back")
        return False

    def fix_outside_lock(self, problem: Problem) -> None:
        """A red check/gate or a conflict is fixed outside the land lock, then the land tries again."""
        e = self.e
        if e.fixes < int(e.cfg.max_fix_rounds):
            cause = {"gate": "gate_red", "verify": "checks_red", "conflict": "conflict"}[problem.kind]
            first = problem.text.strip().splitlines() or [""]
            red = f"gate red on the rebased tree: {first[-1][:200]}"
            e.steps.move("fix", cause, red if problem.kind == "gate" else problem.text.splitlines()[0])
        fixed = e.fixer.fix(problem.kind, problem.text)
        stages = len((e.plan_data or {}).get("stages") or [])
        if problem.kind == "verify" and fixed != "accept":
            e.pending_land_validation += "\n" + e.stuck_why
            e.checkpoints.save(stage=stages, step="land-verify-red")
            raise e.blocked_for("land retry validation fix did not pass its checks and review; branch kept", "FAULT_LAND")
        if problem.kind == "verify":
            e.pending_land_validation = ""
            e.checkpoints.save(stage=stages, step="land")
            if e.git("status", "--porcelain"):  # unlike verification before finish(), a retry check's fix follows the task commit
                e.checkout.stage_all(check=True)
                e.sh(["git", "commit", "-q", "--no-verify", "--amend", "--no-edit"], check=True, pin=True)

