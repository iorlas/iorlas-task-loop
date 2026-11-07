"""Strict bounds on a worker (tl-7y6.24): the engine alone makes branches and worktrees. After a worker call the slot's HEAD must still be
on the task branch (detached only mid-rebase, a conflict fix) and the slot worktree must hold no worktree that was not there before the
call. Worktrees elsewhere are not counted: other slots, base checks and sessions add them to the same repo at any time. Whatever moved
fails the bead (FAULT_ENGINE) with what moved; nothing is repaired."""

from pathlib import Path
from typing import Any


def worktrees(e: Any) -> frozenset[str]:
    """The paths of the repo's worktrees."""
    return frozenset(c.path for c in e.git.checkouts(e.wt))


def rebasing(e: Any) -> bool:
    return bool(e.git.rebasing(e.wt))


def check(e: Any, before: frozenset[str], blocked: Any) -> None:
    """Raise `blocked` (FAULT_ENGINE) naming what a worker call moved: the branch HEAD left, or the worktrees it added."""
    now = e.git.branch(e.wt)
    if e.branch and now != e.branch and not (not now and rebasing(e)):
        raise blocked(f"failed: the worker left {e.branch} for {now or 'a detached HEAD'}", "FAULT_ENGINE")
    inside = Path(e.wt).resolve()
    if added := sorted(p for p in worktrees(e) - before if Path(p).resolve().is_relative_to(inside)):
        raise blocked(f"failed: the worker added worktree {', '.join(added)}", "FAULT_ENGINE")
