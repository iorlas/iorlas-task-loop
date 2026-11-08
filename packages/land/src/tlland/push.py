"""Outbound LFS and bead delivery, recovery of earlier lands, and the push in the lock."""
import os
import shutil
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlkernel import fence
from tlkernel.beadsport import Beads, DoltPush
from tlkernel.branches import task_branch
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.landmatchers import Push, lfs_in, no_dolt_remote
from tlkernel.landmatchers import Push as PushText
from tlkernel.ports import Clock, Sh
from tlkernel.stagefacts import Narrate

from tlland import cleanup
from tlland.gate import GatePass, Problem, ProblemKind
from tlland.host import (
    PUSH_TRIES,
    PUSH_UP_FAILS,
    BeginSteps,
    FetchCheckout,
    Land,
    LandState,
    NetWorker,
    Next,
    OutcomeMoveSteps,
    OutcomeSteps,
    Phase,
)
from tlland.push_evidence import failure


def is_push(argv: list[str]) -> bool:
    return len(argv) > 1 and os.path.basename(argv[0]) == "git" and argv[1] == "push"


def pin_head(land: list[str], sha: str) -> list[str]:
    """A `git push` refspec that names HEAD (`HEAD`, `HEAD:main`, `+HEAD:main`) names `sha` instead: what is pushed is the commit
    resolved before the push, whatever HEAD does meanwhile. Any other command is left as it is."""
    if not is_push(land):
        return list(land)
    return [*land[:2], *(a.replace("HEAD", sha, 1) if a.lstrip("+").partition(":")[0] == "HEAD" else a for a in land[2:])]


def last_fetched(git: Git, wt: str, remote: str, ref: str) -> str:
    """What this clone last fetched of `refs/heads/<x>` on the remote, '' when it never has: the sha a lease push expects."""
    return git.rev_parse(wt, f"refs/remotes/{remote}/{ref.removeprefix('refs/heads/')}") or ""


def target(land: list[str]) -> tuple[str, list[str]] | None:
    """(remote, the refs pushed) from a `git push` argv; HEAD:main pushes HEAD. None for a custom command."""
    if not is_push(land):
        return None
    pos = [a for a in land[2:] if not a.startswith("-")]
    refs = [p.lstrip("+").partition(":")[0] or "HEAD" for p in pos[1:]]
    return (pos[0] if pos else "origin"), (refs or ["HEAD"])


def uses_lfs(wt: str | Path) -> bool:
    try:
        return lfs_in((Path(wt) / ".gitattributes").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


class OutboundBd(Protocol):
    def dolt_push(self) -> DoltPush: ...


class OutboundCheckout(Protocol):
    def stage_all(self, check: bool = ..., everything: bool = ...) -> int: ...


class OutboundTree(Protocol):
    def wip(self, why: str, everything: bool = ...) -> bool: ...


class OutboundSteps(BeginSteps, Protocol):
    def end(self, outcome: str = ...) -> None: ...


class OutboundHost(Protocol):
    """What the pushes read of the engine: the land command, the clock, git, the shell for the land command, bd's dolt push, the log."""



    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def wt(self) -> str: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def git(self) -> Git: ...
    @property
    def dry(self) -> bool: ...
    @property
    def log(self) -> Narrate: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def store(self) -> OutboundBd: ...
    @property
    def checkout(self) -> OutboundCheckout: ...
    @property
    def tree(self) -> OutboundTree: ...
    @property
    def steps(self) -> OutboundSteps: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Outbound:
    def __init__(self, host: OutboundHost) -> None:
        self.e = host

    def lfs_push(self) -> tuple[int, str]:
        """In the lock, right before the push: `git lfs push <remote> <refs>` for the pushed refs only, when the repo uses LFS and the
        land is a `git push`. -> (exit code, tail). A repo that needs LFS on a box without git-lfs is a fault, branch kept."""
        e = self.e
        want = target(e.cfg.land)
        if want is None or not uses_lfs(e.wt):
            return 0, ""
        if shutil.which("git-lfs") is None:
            raise e.blocked_for(
                "failed: .gitattributes puts files in Git LFS but git-lfs is not installed here (install git-lfs); branch kept",
                "FAULT_LAND",
            )
        t0 = e.clock.monotonic()
        done = e.git.lfs_push(e.wt, want[0], want[1])
        e.log.note(f"git lfs push {' '.join([want[0], *want[1]])}: {'ok' if done.ok else 'failed'} in {e.clock.monotonic() - t0:.1f}s")
        return (0, done.output) if done.ok else (1, done.output)

    def wip_push(self, stage: int) -> None:
        """tl-7y6.22: an accepted stage is committed (wip) and the task branch goes to the land's remote, so the work survives a lost box
        and the other machine sees it. Only when the land is a `git push` (a custom command has no remote here), never in a dry run.
        No -u and no git config (the repo's .git/config is shared by every worktree); force-with-lease because the branch is rebased at
        land and at resume. A failure blocks the bead with git's words."""
        e = self.e
        want = target(e.cfg.land)
        if e.dry or want is None:
            return
        e.steps.begin("push", f"push accepted stage {stage}", stage=stage)
        outcome = "failed"
        try:
            self.push_stage(stage, want[0])
            outcome = "done"
        finally:
            e.steps.end(outcome)

    def push_stage(self, stage: int, remote: str) -> None:
        """Commit and push the accepted stage inside its own timed step, including LFS and the pre-push hook."""
        e = self.e
        e.checkout.stage_all()
        if e.git.staged(e.wt):  # staged work: a wip commit of what the stages meant
            e.tree.wip(f"stage {stage} accepted", everything=False)
        ref = f"refs/heads/{task_branch(e.bead)}"
        rc, tail = self.lfs_push()  # git-lfs's hook is not on the hooks path: else the branch lacks its LFS files
        if not rc:
            t0 = e.clock.monotonic()
            done = e.git.push_lease(e.wt, remote, f"HEAD:{ref}", last_fetched(e.git, e.wt, remote, ref))
            rc, tail = (0 if done.ok else 1), done.output
            e.log.note(
                f"git push --force-with-lease={ref}:<last fetched> {remote} HEAD:{ref}: {'ok' if rc == 0 else 'failed'} in "
                f"{e.clock.monotonic() - t0:.1f}s"
            )
        why = failure(tail, e.run_dir, ref) if rc else ""
        if rc and any(w in tail for w in ("stale info", "non-fast-forward", "fetch first")):
            # the remote branch was pushed from another machine and this clone has no copy of it
            raise e.blocked_for(f"failed: {ref} on {remote} holds work this clone has never fetched (another machine ran this bead); "
                                f"fetch it and decide which work to keep, then rerun\n{why}", "FAULT_LAND")
        if rc:
            kind = "PAUSE_NETWORK" if Push.transient(tail) else "FAULT_LAND"
            raise e.blocked_for(f"{'paused' if kind == 'PAUSE_NETWORK' else 'failed'}: the work-in-progress push of {ref} to {remote} "
                                f"failed after stage {stage}; the branch is kept, the next run continues it\n{why}", kind)

    def bd_sync(self, sha: str) -> None:
        """After the land, outside the lock: `bd sync` (pull, then push; bd's own `dolt push` exits 0 on a rejection). No remote is a
        quiet
        no-op; a failure blocks the bead (tl-7y6.21: a warning let a box that cannot reach the remote keep every bead to itself).
        The rerun finds the land, pushes again."""
        e = self.e
        t0 = e.clock.monotonic()
        try:
            rc, text = e.store.dolt_push()  # (code, bd's words)
        except Exception as err:  # bd itself failed: the same block, the land stands
            rc, text = 1, str(err)
        if rc == 1 and no_dolt_remote(text):  # an error only: a conflict (2), retries exhausted (3), stuck (4) are never "no remote"
            return
        e.log.note(f"bd sync: {'ok' if rc == 0 else 'failed'} in {e.clock.monotonic() - t0:.1f}s")
        if rc != 0:
            raise e.blocked_for(f"failed: landed {sha[:12]}, but bd sync after the land failed (exit {rc}; fix bd's Dolt remote, then "
                                f"rerun: the rerun finds the land and pushes again)\n{text.strip()}", "PAUSE_NETWORK")


class LandedConfig(Protocol):
    @property
    def base(self) -> str: ...
    @property
    def land(self) -> list[str]: ...


class LandedHost(Protocol):
    """What the look for an earlier push reads of the engine: the bead, the base, git, the fetch, and the landed sha it sets."""

    landed_sha: str  # set the moment the push goes through
    land_state: LandState

    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> LandedConfig: ...
    @property
    def dry(self) -> bool: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def checkout(self) -> FetchCheckout: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    def warn(self, text: str) -> None: ...


class Landed:
    def __init__(self, host: LandedHost) -> None:
        self.e = host

    def already(self, fetch: bool = True) -> str:
        """tl-7y6.2.13: a push that died of the network after origin took it. The task branch's tip is the land commit (titled
        `... (<bead>)`) and it is on the base: it landed, and nothing is pushed twice. -> its sha, or ''."""
        e = self.e
        if e.dry or (fetch and e.checkout.fetch()[0]):
            return ""
        last = e.git.log(e.wt, ["HEAD"], limit=1)
        if not last or not last[0].subject.endswith(f"({e.bead})"):
            return ""
        tip = last[0].oid
        want = target(e.cfg.land)
        branch = e.git.branch(e.wt) if want else ""
        e.land_state.remote_oid = cleanup.remote_oid(e.git, e.wt, want[0], branch) if want and branch else ""
        return tip if e.git.is_ancestor(e.wt, tip, e.cfg.base) else ""

    def found(self, sha: str) -> str:
        e = self.e
        e.landed_sha = sha
        e.steps.outcome("landed", sha[:12])
        e.warn(f"the push had already gone through ({sha[:12]} is on {e.cfg.base}): not pushed again")
        return sha


PUSH_TIMEOUT_S = 600.0  # the land command's own limit (the default is an hour: a push stuck on a remote ate 25-48 min, tl-bxk.10.33.1)
SLOW_PUSH_S = 30.0  # a push (LFS upload plus land command) that takes longer than this says where its time went


class PushConfig(LandedConfig, Protocol):
    @property
    def land(self) -> list[str]: ...


class Lfs(Protocol):
    def lfs_push(self) -> tuple[int, str]: ...


class PushHost(Protocol):
    """What the push reads of the engine: the base and the land command, git and the shell for the land command, the fence, the stop point,
    the steps and warnings; the landed sha it sets; the network probe."""

    landed_sha: str  # set the moment the push goes through
    land_state: LandState
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
    @property
    def run_dir(self) -> Path: ...
    def warn(self, text: str) -> None: ...
    def stop_deferred(self) -> AbstractContextManager[list[bool]]: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


def stale(git: Git, wt: str, base_ref: str, gate_pass: GatePass) -> Problem | None:
    """A stale Problem when the tree or the base is no longer the one the pass is for (nothing may be sent), else None."""
    tree, base = git.rev_parse(wt, "HEAD^{tree}"), git.rev_parse(wt, base_ref)
    if (tree, base) == (gate_pass.tree, gate_pass.base):
        return None
    was, now = f"{gate_pass.tree[:12]} on {gate_pass.base[:12]}", f"{tree[:12]} on {base[:12]}"
    return Problem(ProblemKind.STALE, f"the gate passed tree {was}; now {now}")


class Pusher:
    def __init__(self, host: PushHost, out: Lfs, clock: Callable[[], float] = time.monotonic) -> None:
        self.e = host
        self.out = out
        self.clock = clock

    def push(self, st: Land, gate_pass: GatePass) -> str | Problem | Next:
        """-> the sha landed; Next.AGAIN rejected, try again; Next.REST a network error, rest first; a stale Problem when the tree or the
        base is no longer the one the pass is for (nothing is pushed). Anything else raises."""
        e = self.e
        problem = stale(e.git, e.wt, e.cfg.base, gate_pass)
        if problem is not None:
            return problem
        fence.check(e.store, e.claim)  # a run whose bead or slot was taken again pushes nothing (Fenced; RunOnce closes nothing)
        want = target(e.cfg.land)
        e.land_state.remote_oid = cleanup.remote_oid(e.git, e.wt, want[0], e.task_branch) if want and e.task_branch else ""
        with e.stop_deferred() as stop:  # a push half done is no state to stop in: finish it, then stop
            t0 = self.clock()
            lrc, ltail = self.out.lfs_push()  # the pushed ref's LFS objects first: the push must not point at objects origin lacks
            t1 = self.clock()
            sha = e.git.rev_parse(e.wt, "HEAD")  # the commit pushed, named in the refspec
            # push_request strips diagnostics; push_refspecs also drops successful hook output and adds processes.
            # Keep configured commands here until the Git port can return the complete captured-SHA request outcome.
            rc, tail = e.sh(pin_head(e.cfg.land, sha), pin=True, timeout=PUSH_TIMEOUT_S) if lrc == 0 else (lrc, ltail)
            self.say_if_slow(t1 - t0, self.clock() - t1, rc, tail)
            if rc != 0:
                sha = ""
            else:
                e.landed_sha = sha
        if rc == 0:
            e.steps.outcome("landed", sha[:12])
            if stop:
                e.warn("a stop came during the land: landed first, closing now")
            return sha
        why = failure(tail, e.run_dir, e.task_branch)
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)\n" + why, "PAUSE_KILLED")
        if lrc or not PushText.rejected(tail):
            self.not_rejected(st, tail, "git lfs push failed" if lrc else "land failed", why)
            return Next.REST
        st.pushes += 1
        e.steps.outcome("rejected", "main moved")
        if st.pushes >= PUSH_TRIES:
            raise e.blocked_for("land rejected 3 times: main moves too fast\n" + why, "FAULT_LAND")
        e.warn(f"push rejected (main moved), try {st.pushes + 1} of {PUSH_TRIES}")
        e.steps.move("land", "push_race", f"push rejected (main moved): try {st.pushes + 1} of {PUSH_TRIES}")
        return Next.AGAIN

    def say_if_slow(self, lfs_s: float, land_s: float, rc: int, tail: str) -> None:
        """A push over SLOW_PUSH_S: the seconds of the LFS upload and of the land command (hook, network and remote are inside the
        command), and what ended it."""
        if lfs_s + land_s <= SLOW_PUSH_S:
            return
        ended = ("pushed" if rc == 0 else "timed out" if rc == 124 else "rejected (main moved)" if PushText.rejected(tail)
                 else "network error" if PushText.transient(tail) else f"failed (exit {rc})")
        self.e.warn(f"slow push: lfs {lfs_s:.0f}s, land command {land_s:.0f}s, {ended}")

    def not_rejected(self, st: Land, tail: str, what: str = "land failed", why: str = "") -> None:
        """A push that failed for another reason: a network error rests, anything else is a fault."""
        e = self.e
        why = why or failure(tail, e.run_dir, e.task_branch)
        if not PushText.transient(tail):
            raise e.blocked_for(what + "\n" + why, "FAULT_LAND")
        if e.worker.acts.net_up() is not False:  # the probe cannot see the fault: counted, a proxy or DNS looks like this
            st.flaky += 1
        if st.flaky >= PUSH_UP_FAILS:
            raise e.blocked_for(f"paused: the land push failed {st.flaky} times with a network error while the network looks up; "
                                f"the branch is kept and the next run lands it again: {why}", "PAUSE_NETWORK")
        st.phase = Phase.NET_DOWN
        e.warn(f"the push failed with a network error, trying again when the network is back: {why}")
        e.steps.move("land", "push_network", "network error on the push; the land looks again after the network is back")
