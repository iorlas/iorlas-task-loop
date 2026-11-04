"""Primitive checkout and branch operations over the pinned git runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.errors import BranchPinned, MissingRevision
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Literal

    from git_porcelain.api import Sha
    from git_porcelain.real import RealRepo, RealWorktree


def branch(wt: RealWorktree) -> str | None:
    """Read symbolic HEAD, including an unborn branch."""
    done = wt.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if done.rc == 1 and not done.out and not done.err:
        return None
    if done.rc:
        raise unavailable(("symbolic-ref",), done)
    return done.out.removesuffix("\n")


def resolve_commit(wt: RealWorktree, ref: str) -> str:
    """Validate a revision without option parsing and return its commit OID."""
    done = wt.run("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", check=False)
    if done.rc:
        error = unavailable(("rev-parse",), done)
        if "Needed a single revision" in done.err or "expected commit type" in done.err:
            raise MissingRevision(str(error))
        raise error
    return done.out.strip()


def checkout(wt: RealWorktree, ref: str) -> None:
    """Switch to an existing branch or detach at a commit, without DWIM branch creation."""
    try:
        resolve_commit(wt, ref)
        wt.run("checkout", "-q", "--no-guess", ref, "--")
    finally:
        wt.repo.invalidate()


def checkout_new(wt: RealWorktree, branch: str, start: str) -> None:
    """Create and check out a branch exclusively."""
    try:
        target = resolve_commit(wt, start)
        wt.run("checkout", "-q", "-b", branch, target, "--")
    finally:
        wt.repo.invalidate()


def clean(wt: RealWorktree, keep: Sequence[str], *, ignored: bool) -> None:
    """Remove untracked files, preserving the supplied exclusion patterns."""
    try:
        wt.run("clean", "-fdxq" if ignored else "-fdq", *(arg for pattern in keep for arg in ("-e", pattern)))
    finally:
        wt.repo.invalidate()


def reset(wt: RealWorktree, rev: str, *, mode: Literal["soft", "mixed", "hard"]) -> None:
    """Reset HEAD and, depending on mode, the index and tracked files."""
    if mode not in {"soft", "mixed", "hard"}:
        msg = f"unknown reset mode: {mode!r}"
        raise ValueError(msg)
    try:
        target = resolve_commit(wt, rev)
        wt.run("reset", "-q", f"--{mode}", target)
    finally:
        wt.repo.invalidate()


def checkout_force(wt: RealWorktree, branch: str, start: str) -> None:
    """Discard local changes and create or reset the checked out branch."""
    try:
        target = resolve_commit(wt, start)
        wt.run("checkout", "-q", "-f", "-B", branch, target, "--")
    finally:
        wt.repo.invalidate()


def rename_branch(repo: RealRepo, old: str, new: str) -> None:
    """Rename a branch without overwriting its destination."""
    try:
        repo.run(repo.path, "rev-parse", "--git-dir")
        repo.run(repo.path, "branch", "-m", "--", old, new)
    finally:
        repo.invalidate()


def delete_branch(repo: RealRepo, branch: str, *, expected: Sha) -> None:
    """Atomically compare and delete a local branch ref."""
    if not expected:
        msg = "expected must be a nonempty commit sha"
        raise ValueError(msg)
    try:
        repo.run(repo.path, "rev-parse", "--git-dir")
        for worktree in repo.worktrees():
            if worktree.branch == branch:
                msg = f"branch {branch!r} is checked out at {worktree.path}"
                raise BranchPinned(msg, str(worktree.path))
        repo.run(repo.path, "update-ref", "-d", f"refs/heads/{branch}", str(expected))
    finally:
        repo.invalidate()
