"""The slot's tree between runs: reset onto the task branch, the wip commit that saves a stopped run's work, leaving the slot."""
import shutil
import time
from pathlib import Path
from typing import Protocol

from taskloop.app.land.gitcall import must
from taskloop.app.land.parts import BeginSteps, FetchCheckout, StageCheckout
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import TASK_EXCLUDE
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.runlog import RunLog


class TreeConfig(Protocol):
    @property
    def base(self) -> str: ...


class TreeCheckout(FetchCheckout, StageCheckout, Protocol):
    def dirty_status(self) -> str: ...


class TreeBriefs(Protocol):
    def export(self) -> object: ...


class TreeHost(Protocol):
    """What the slot's tree reads of the engine: the bead, the slot and its task folder, the base, git, the checkout, the
    briefs, the log; the branch and the dirty flag it sets."""

    left_dirty: bool  # the slot held work from an earlier run, saved as a wip commit
    branch: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def wt(self) -> str: ...
    @property
    def task_dir(self) -> Path: ...
    @property
    def fresh(self) -> bool: ...
    @property
    def cfg(self) -> TreeConfig: ...
    @property
    def git(self) -> Git: ...
    @property
    def steps(self) -> BeginSteps: ...
    @property
    def checkout(self) -> TreeCheckout: ...
    @property
    def briefs(self) -> TreeBriefs: ...
    @property
    def log(self) -> RunLog: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Tree:
    def __init__(self, host: TreeHost) -> None:
        self.e = host

    def reset(self, bead: Bead) -> str:
        """The first node: fetch, make the slot's tree the task branch (resumed, or started again on the base) and clear the task folder."""
        e = self.e
        e.steps.begin("reset", "reset")
        branch = bead.metadata.get("branch") or "task/" + e.bead
        e.checkout.fetch(check=True)
        self.exclude_task_folder()
        exists = e.git.has_branch(e.wt, branch)
        e.left_dirty = False
        if e.checkout.dirty_status():
            self.save_other_work(branch)
        if exists and e.fresh:
            self.keep_aside(branch)
            exists = False
        if exists:
            self.free_branch(branch)
            must(e, f"checkout {branch}", lambda: e.git.checkout(e.wt, branch))
        else:
            must(e, f"checkout -B {branch} {e.cfg.base}", lambda: e.git.checkout_reset(e.wt, branch, e.cfg.base))
        for old in e.task_dir.iterdir():  # earlier runs' files are no facts; only the writer's evidence carries over
            if old.name != "evidence":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        e.briefs.export()
        e.branch = branch
        return branch

    def exclude_task_folder(self) -> None:
        e = self.e
        exclude = Path(e.git.common_dir(e.wt)) / "info" / "exclude"
        if TASK_EXCLUDE not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a") as f:
                f.write(f"\n{TASK_EXCLUDE}\n")

    def save_other_work(self, branch: str) -> None:
        """Uncommitted work in the slot: the branch's own is saved as a wip commit, another branch's stops the run."""
        e = self.e
        if e.git.branch(e.wt) != branch:
            raise e.blocked_for(f"failed: worktree {e.wt} has uncommitted work of another branch", "FAULT_SLOT")
        self.wip("left from an earlier run")
        e.left_dirty = True

    def keep_aside(self, branch: str) -> None:
        """tl-19i: --fresh starts the task again on the base: the old branch is kept as task/<id>-stale-<time>, never reset in place
        and never checked out (lifesim-6pld ran --fresh on its old branch, 56 commits behind, and failed on a missing recipe)."""
        e = self.e
        self.free_branch(branch)
        if e.git.count(e.wt, [branch], [e.cfg.base]) == 0:
            return
        stale = f"{branch}-stale-{time.strftime('%Y%m%d-%H%M%S')}"
        if e.git.has_branch(e.wt, stale):
            stale += "-2"
        try:
            e.git.rename_branch(e.wt, branch, stale)
        except SlotGitError as err:
            raise e.blocked_for(
                f"failed: --fresh could not keep the old branch aside as {stale}: {str(err).strip()[-200:]}", "FAULT_SLOT"
            ) from err
        e.log.note(f"--fresh: the old branch {branch} is kept as {stale}; the task starts again on {e.cfg.base}")
        e.comment(f"Fresh (engine): --fresh: the earlier work on {branch} is kept as the branch {stale}; "
                  f"the task starts again on {e.cfg.base}.")

    def free_branch(self, branch: str) -> None:
        """A paused bead resumes in any free slot: the slot that last held its branch lets go of it (detached there),
        unless that slot has uncommitted work, which is never touched."""
        e = self.e
        here = str(Path(e.wt).resolve())
        for there in e.git.checkouts(e.wt):
            if there.branch == branch and str(Path(there.path).resolve()) != here:
                if e.git.dirty(there.path):
                    raise e.blocked_for(
                        f"failed: {branch} is checked out in {there.path} with uncommitted work; commit or clean it there", "FAULT_SLOT"
                    )
                e.git.checkout_detached(there.path, "HEAD")
                e.log.note(f"{branch} was checked out in {there.path}: detached it there to resume here")

    def wip(self, why: str, everything: bool = True) -> bool:
        """Save the slot's work as a commit on its branch (nothing the bead made is left behind in a slot that is reset to the base).
        everything=False: only what a stage meant (a mid-run save; the strays are quarantined at the land, not committed)."""
        e = self.e
        e.checkout.stage_all(everything=everything)  # tl-g6a
        # --no-verify: a wip commit saves work, it does not judge it; a pre-commit hook that refused it left staged files in the
        # slot and failed the next bead there (lifesim-6pld, then rl4s)
        done = e.git.try_commit(e.wt, f"wip ({e.bead}): {why}", verify=False)
        if not done.ok:
            e.warn(f"the wip commit ({why}) failed, the work stays uncommitted in {e.wt}: {done.output.strip()[-300:]}")
            e.log.note(f"wip commit failed: {done.output.strip()[-300:]}")
        return done.ok

    def leave_slot(self, outcome: str, branch: str) -> None:
        """tl-g6a: a bead that parked leaves its work on its own branch (wip committed) and the slot at the detached base,
        not on an old branch whose untracked files made the next runs fail as 'uncommitted work of another branch'."""
        e = self.e
        if outcome in ("landed", "done") or not branch or branch != (e.branch or None):
            return
        if e.checkout.dirty_status() or e.git.branch(e.wt) != branch:
            return  # work that could not be committed, or files stage_all left out, stay where they are for the next run
        try:
            e.git.checkout_detached(e.wt, e.cfg.base)
        except SlotGitError as err:
            e.warn(f"the slot could not be left at the base: {str(err).strip()[-160:]}")
