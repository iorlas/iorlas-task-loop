"""Pinned worktree pool operations and raw status state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.errors import GitUnavailable, NotARepo, WorktreeRemoveRefused
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from pathlib import Path

    from git_porcelain.real import RealRepo, RealWorktree

__all__ = ["add_worktree", "drop_worktree", "prune_worktrees", "worktree_state"]


def add_worktree(repo: RealRepo, path: Path, rev: str, *, force: bool) -> RealWorktree:
    try:
        repo.run(repo.path, "worktree", "add", "-q", "--detach", *(["--force"] if force else []), str(path), rev)
    finally:
        repo.invalidate()
    return repo.worktree(path)


def drop_worktree(repo: RealRepo, path: Path, *, force: bool, missing_ok: bool) -> None:
    try:
        if not missing_ok or path.exists():
            args = ("worktree", "remove", *(["--force"] if force else []), str(path))
            done = repo.run(repo.path, *args, check=False)
            if done.rc:
                error = unavailable(args, done)
                if type(error) is not GitUnavailable:
                    raise error
                lines = done.err.strip().splitlines()
                raise WorktreeRemoveRefused(lines[-1] if lines else "git worktree remove failed")
        if missing_ok:
            repo.run(repo.path, "worktree", "prune")
    finally:
        repo.invalidate()


def prune_worktrees(repo: RealRepo) -> None:
    try:
        repo.run(repo.path, "worktree", "prune")
    finally:
        repo.invalidate()


def worktree_state(repo: RealRepo, path: Path) -> bytes | None:
    args = ("--no-optional-locks", "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
    done = repo.run(path, *args, check=False)
    if done.rc == 0:
        return done.raw
    error = unavailable(args, done)
    if isinstance(error, NotARepo) or done.err.strip() == "fatal: this operation must be run in a work tree":
        return None
    raise error
