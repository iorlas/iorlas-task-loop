"""Primitive checkout and branch operations on the in-memory git state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.errors import BranchExists, BranchPinned, GitUnavailable, MissingRevision, RefRace
from git_porcelain.fake_ops import branch_ref, check_branch_free, hard_to, require_index, switch_tree
from git_porcelain.fake_read import resolve_commit

if TYPE_CHECKING:
    from typing import Literal

    from git_porcelain.api import Sha
    from git_porcelain.fake_store import CheckoutState, RepoState


def branch(wt: CheckoutState) -> str | None:
    """Return the symbolic HEAD's branch name even before its first commit."""
    return wt.head_ref.removeprefix("refs/heads/") if wt.head_ref else None


def checkout(repo: RepoState, wt: CheckoutState, ref: str) -> None:
    """Check out an existing local branch or detach at a resolved commit."""
    target = resolve_commit(repo, wt, ref)
    local = branch_ref(ref)
    # A fully qualified ref is a commit-ish for checkout, rather than a short branch name.
    symbolic = local if local in repo.refs else None
    if ref == "HEAD":
        symbolic = wt.head_ref
    if symbolic:
        check_branch_free(repo, wt, symbolic)
    require_index(wt)
    switch_tree(repo, wt, repo.store.commits[target].files, repo.head_files(wt))
    wt.head_ref, wt.detached = symbolic, None if symbolic else target


def checkout_new(repo: RepoState, wt: CheckoutState, branch: str, start: str) -> None:
    """Create a branch exclusively and switch only after all checks pass."""
    target = resolve_commit(repo, wt, start)
    ref = branch_ref(branch)
    if ref in repo.refs:
        msg = f"a branch named '{branch}' already exists"
        raise BranchExists(msg)
    require_index(wt)
    switch_tree(repo, wt, repo.store.commits[target].files, repo.head_files(wt))
    repo.refs[ref] = target
    wt.head_ref, wt.detached = ref, None


def reset(repo: RepoState, wt: CheckoutState, rev: str, *, mode: Literal["soft", "mixed", "hard"]) -> None:
    """Move HEAD, optionally replacing the index and tracked working files."""
    if mode not in {"soft", "mixed", "hard"}:
        msg = f"unknown reset mode: {mode!r}"
        raise ValueError(msg)
    target = resolve_commit(repo, wt, rev)
    if mode != "soft":
        require_index(wt)
    elif wt.unmerged:
        msg = "cannot do a soft reset in the middle of a merge"
        raise GitUnavailable(msg)
    tree = repo.store.commits[target].files
    if mode == "hard":
        hard_to(repo, wt, tree, repo.head_files(wt))
    elif mode == "mixed":
        wt.index = dict(tree)
        wt.unmerged.clear()
    repo.move_head(wt, target)


def checkout_force(repo: RepoState, wt: CheckoutState, branch: str, start: str) -> None:
    """Force checkout of a new or reset branch; another worktree still pins it."""
    target = resolve_commit(repo, wt, start)
    ref = branch_ref(branch)
    check_branch_free(repo, wt, ref)
    require_index(wt)
    hard_to(repo, wt, repo.store.commits[target].files, repo.head_files(wt))
    repo.refs[ref] = target
    wt.head_ref, wt.detached = ref, None


def rename_branch(repo: RepoState, wt: CheckoutState, old: str, new: str) -> None:
    """Rename a branch and update every symbolic HEAD that refers to it."""
    source, dest = branch_ref(old), branch_ref(new)
    if source not in repo.refs and wt.head_ref != source:
        msg = f"no branch named '{old}'"
        raise MissingRevision(msg)
    if source != dest and dest in repo.refs:
        msg = f"a branch named '{new}' already exists"
        raise BranchExists(msg)
    if source in repo.refs:
        repo.refs[dest] = repo.refs.pop(source)
    for other in repo.worktrees.values():
        if other.head_ref == source:
            other.head_ref = dest


def delete_branch(repo: RepoState, branch: str, *, expected: Sha) -> None:
    """Compare and delete the local ref; a stale or absent tip is never retryable."""
    if not expected:
        msg = "expected must be a nonempty commit sha"
        raise ValueError(msg)
    ref = branch_ref(branch)
    for worktree in repo.worktrees.values():
        if worktree.head_ref == ref:
            msg = f"branch {branch!r} is checked out at {worktree.path}"
            raise BranchPinned(msg, str(worktree.path))
    if repo.refs.get(ref) != expected:
        msg = f"cannot lock ref '{ref}': expected {expected}, found {repo.refs.get(ref)}"
        raise RefRace(msg)
    del repo.refs[ref]
