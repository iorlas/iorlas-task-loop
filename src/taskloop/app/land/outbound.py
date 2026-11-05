"""What leaves the machine at a land besides the commit: the push argv, the LFS objects of the pushed ref before the push,
and bd's Dolt data after it. Delivery still consults the application judge through the installed hook."""
import os
import shutil
from pathlib import Path
from typing import Protocol

from taskloop.app.land.parts import BeginSteps
from taskloop.app.land.push_evidence import failure
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Clock, DoltPush, Git
from taskloop.domain.land.matchers import Push, lfs_in, no_dolt_remote
from taskloop.stores.runlog import RunLog


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
    def log(self) -> RunLog: ...
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
        ref = f"refs/heads/task/{e.bead}"
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
