"""Strict bounds on a worker (tl-7y6.24): the engine alone makes branches and worktrees. After a worker call the slot's HEAD must still be
on the task branch (detached only mid-rebase, a conflict fix) and the slot worktree must hold no worktree that was not there before the
call. Worktrees elsewhere are not counted: other slots, base checks and sessions add them to the same repo at any time. Whatever moved
fails the bead (FAULT_ENGINE) with what moved; nothing is repaired."""

from pathlib import Path
from typing import Any


def worktrees(e: Any) -> frozenset[str]:
    """The paths in `git worktree list --porcelain` of the repo."""
    return frozenset(ln[len("worktree "):] for ln in e.git("worktree", "list", "--porcelain").splitlines() if ln.startswith("worktree "))


def rebasing(e: Any) -> bool:
    gd = Path(e.git("rev-parse", "--absolute-git-dir") or ".")
    return (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists()


def check(e: Any, before: frozenset[str], blocked: Any) -> None:
    """Raise `blocked` (FAULT_ENGINE) naming what a worker call moved: the branch HEAD left, or the worktrees it added."""
    now = e.git("symbolic-ref", "--short", "-q", "HEAD")
    if e.branch and now != e.branch and not (not now and rebasing(e)):
        raise blocked(f"failed: the worker left {e.branch} for {now or 'a detached HEAD'}", "FAULT_ENGINE")
    inside = Path(e.wt).resolve()
    if added := sorted(p for p in worktrees(e) - before if Path(p).resolve().is_relative_to(inside)):
        raise blocked(f"failed: the worker added worktree {', '.join(added)}", "FAULT_ENGINE")
