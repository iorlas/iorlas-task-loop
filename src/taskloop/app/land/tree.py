"""The slot's tree between runs: reset onto the task branch, the wip commit that saves a stopped run's work, leaving the slot."""
import shutil
import time
from pathlib import Path
from typing import Any

from taskloop.contracts.paths import TASK_EXCLUDE


class Tree:
    def __init__(self, host: Any) -> None:
        self.e = host

    def reset(self, bead: Any) -> str:
        """The first node: fetch, make the slot's tree the task branch (resumed, or started again on the base) and clear the task folder."""
        e = self.e
        e.steps.begin("reset", "reset")
        branch = bead.metadata.get("branch") or "task/" + e.bead
        e.checkout.fetch(check=True)
        self.exclude_task_folder()
        exists = bool(e.git("rev-parse", "--verify", "-q", "refs/heads/" + branch))
        e.left_dirty = False
        if e.checkout.dirty_status():
            self.save_other_work(branch)
        if exists and e.fresh:
            self.keep_aside(branch)
            exists = False
        if exists:
            self.free_branch(branch)
            e.sh(["git", "checkout", "-q", branch], check=True, pin=True)
        else:
            e.sh(["git", "checkout", "-q", "-B", branch, e.cfg.base], check=True, pin=True)
        for old in e.task_dir.iterdir():  # earlier runs' files are no facts; only the writer's evidence carries over
            if old.name != "evidence":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        e.briefs.export()
        e.branch = branch
        return branch

    def exclude_task_folder(self) -> None:
        e = self.e
        exclude = Path(e.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info" / "exclude"
        if TASK_EXCLUDE not in (exclude.read_text() if exclude.exists() else ""):
            with open(exclude, "a") as f:
                f.write(f"\n{TASK_EXCLUDE}\n")

    def save_other_work(self, branch: str) -> None:
        """Uncommitted work in the slot: the branch's own is saved as a wip commit, another branch's stops the run."""
        e = self.e
        if e.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
            raise e.blocked_for(f"failed: worktree {e.wt} has uncommitted work of another branch", "FAULT_SLOT")
        self.wip("left from an earlier run")
        e.left_dirty = True

    def keep_aside(self, branch: str) -> None:
        """tl-19i: --fresh starts the task again on the base: the old branch is kept as task/<id>-stale-<time>, never reset in place
        and never checked out (lifesim-6pld ran --fresh on its old branch, 56 commits behind, and failed on a missing recipe)."""
        e = self.e
        self.free_branch(branch)
        if e.git("rev-list", "--count", f"{e.cfg.base}..{branch}") in ("", "0"):
            return
        stale = f"{branch}-stale-{time.strftime('%Y%m%d-%H%M%S')}"
        if e.git("rev-parse", "--verify", "-q", "refs/heads/" + stale):
            stale += "-2"
        rc, tail = e.sh(["git", "branch", "-m", branch, stale], pin=True)
        if rc:
            raise e.blocked_for(f"failed: --fresh could not keep the old branch aside as {stale}: {tail.strip()[-200:]}", "FAULT_SLOT")
        e.log.note(f"--fresh: the old branch {branch} is kept as {stale}; the task starts again on {e.cfg.base}")
        e.comment(f"Fresh (engine): --fresh: the earlier work on {branch} is kept as the branch {stale}; "
                  f"the task starts again on {e.cfg.base}.")

    def free_branch(self, branch: str) -> None:
        """A paused bead resumes in any free slot: the slot that last held its branch lets go of it (detached there),
        unless that slot has uncommitted work, which is never touched."""
        e = self.e
        here, path = str(Path(e.wt).resolve()), None
        for line in (e.git("worktree", "list", "--porcelain") or "").splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
            elif line == "branch refs/heads/" + branch and path and str(Path(path).resolve()) != here:
                if e.git_in(path, "status", "--porcelain"):
                    raise e.blocked_for(f"failed: {branch} is checked out in {path} with uncommitted work; commit or clean it there",
                                        "FAULT_SLOT")
                e.git_in(path, "checkout", "-q", "--detach")
                e.log.note(f"{branch} was checked out in {path}: detached it there to resume here")

    def wip(self, why: str) -> bool:
        """Save the slot's work as a commit on its branch (nothing the bead made is left behind in a slot that is reset to the base)."""
        e = self.e
        e.checkout.stage_all(everything=True)  # tl-g6a
        # --no-verify: a wip commit saves work, it does not judge it; a pre-commit hook that refused it left staged files in the
        # slot and failed the next bead there (lifesim-6pld, then rl4s)
        rc, tail = e.sh(["git", "commit", "-q", "--no-verify", "-m", f"wip ({e.bead}): {why}"], pin=True)
        if rc:
            e.warn(f"the wip commit ({why}) failed, the work stays uncommitted in {e.wt}: {(tail or '').strip()[-300:]}")
            e.log.note(f"wip commit failed: {(tail or '').strip()[-300:]}")
        return rc == 0

    def leave_slot(self, outcome: str, branch: str) -> None:
        """tl-g6a: a bead that parked leaves its work on its own branch (wip committed) and the slot at the detached base,
        not on an old branch whose untracked files made the next runs fail as 'uncommitted work of another branch'."""
        e = self.e
        if outcome in ("landed", "done") or not branch or branch != (e.branch or None):
            return
        if e.checkout.dirty_status() or e.git("symbolic-ref", "--short", "-q", "HEAD") != branch:
            return  # work that could not be committed, or files stage_all left out, stay where they are for the next run
        rc, tail = e.sh(["git", "checkout", "-q", "--detach", e.cfg.base], pin=True)
        if rc:
            e.warn(f"the slot could not be left at the base: {tail.strip()[-160:]}")
