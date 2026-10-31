"""The push in the lock: the pass's tree on its base, the LFS objects first, then the land command; what a rejection or a network error
asks of the land. Nothing is pushed twice, and a stop waits for a push that is half done."""
from contextlib import AbstractContextManager
from typing import Protocol

from taskloop.app.land import cleanup
from taskloop.app.land.gate import GatePass, Problem, ProblemKind
from taskloop.app.land.landed import LandedConfig
from taskloop.app.land.outbound import LAND_ENV, pin_head, target
from taskloop.app.land.parts import NetWorker, OutcomeMoveSteps
from taskloop.app.land.state import PUSH_TRIES, PUSH_UP_FAILS, Land, Next, Phase
from taskloop.contracts import fence
from taskloop.contracts.ports import Beads, Git, Sh
from taskloop.domain.land.matchers import Push as PushText


class PushConfig(LandedConfig, Protocol):
    @property
    def land(self) -> list[str]: ...


class Lfs(Protocol):
    def lfs_push(self) -> tuple[int, str]: ...


class PushHost(Protocol):
    """What the push reads of the engine: the base and the land command, git and the shell for the land command, the fence, the stop point,
    the steps and warnings; the landed sha it sets; the network probe."""

    landed_sha: str  # set the moment the push goes through
    land_remote_oid: str  # the task ref checked before the push; cleanup retains this lease
    task_branch: str

    @property
    def cfg(self) -> PushConfig: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def store(self) -> Beads: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def steps(self) -> OutcomeMoveSteps: ...
    @property
    def worker(self) -> NetWorker: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def warn(self, text: str) -> None: ...
    def stop_deferred(self) -> AbstractContextManager[list[bool]]: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Pusher:
    def __init__(self, host: PushHost, out: Lfs) -> None:
        self.e = host
        self.out = out

    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next:
        """-> the sha landed; Next.AGAIN rejected, try again; Next.REST a network error, rest first; a stale Problem when the tree or the
        base is no longer the one the pass is for (nothing is pushed). Anything else raises."""
        e = self.e
        tree, base = e.git.rev_parse(e.wt, "HEAD^{tree}"), e.git.rev_parse(e.wt, e.cfg.base)
        if (tree, base) != (gate_pass.tree, gate_pass.base):
            now = f"{tree[:12]} on {base[:12]}"
            return Problem(ProblemKind.STALE, f"the gate passed tree {gate_pass.tree[:12]} on {gate_pass.base[:12]}; now {now}")
        fence.check(e.store, e.claim)  # a run whose bead or slot was taken again pushes nothing (Fenced; RunOnce closes nothing)
        want = target(e.cfg.land)
        e.land_remote_oid = cleanup.remote_oid(e.git, e.wt, want[0], e.task_branch) if want and e.task_branch else ""
        with e.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
            lrc, ltail = self.out.lfs_push()  # the pushed ref's LFS objects first: the push must not point at objects origin lacks
            sha = e.git.rev_parse(e.wt, "HEAD")  # the commit pushed, named in the refspec
            rc, tail = e.sh(pin_head(e.cfg.land, sha), pin=True, env=LAND_ENV) if lrc == 0 else (lrc, ltail)  # TL_LAND: the hook lets it by
            if rc != 0:
                sha = ""
            else:
                e.landed_sha = sha
        if rc == 0:
            e.steps.outcome("landed", sha[:12])
            if stop:
                e.warn("a stop came during the land: landed first, closing now")
            return sha
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)", "PAUSE_KILLED")
        if lrc or not PushText.rejected(tail):
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
        if not PushText.transient(tail):
            raise e.blocked_for(what + "\n" + tail, "FAULT_LAND")
        if e.worker.acts.net_up() is not False:  # the probe cannot see the fault: counted, a proxy or DNS looks like this
            st.flaky += 1
        if st.flaky >= PUSH_UP_FAILS:
            raise e.blocked_for(f"paused: the land push failed {st.flaky} times with a network error while the network looks up; "
                                f"the branch is kept and the next run lands it again: {tail.strip()[-200:]}", "PAUSE_NETWORK")
        st.phase = Phase.NET_DOWN
        e.warn(f"the push failed with a network error, trying again when the network is back: {tail.strip()[-160:]}")
        e.steps.move("land", "push_network", "network error on the push; the land looks again after the network is back")
