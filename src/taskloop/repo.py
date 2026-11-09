"""Readonly inspection of an explicitly selected checkout through the shared Git API."""

from dataclasses import dataclass
from pathlib import Path
from typing import NewType

from git_porcelain import Repo

RepoId = NewType("RepoId", str)


@dataclass(frozen=True)
class RepoInspection:
    """Local identity and selected checkout; this does not authorize execution."""

    repo_id: RepoId
    common_dir: Path
    checkout_path: Path
    origin_url: str | None


class UnsupportedCheckout(ValueError):
    """The selection is not an explicit working checkout root."""


def inspect_repo(repo: Repo, checkout_path: Path) -> RepoInspection:
    """Observe identity and worktrees once, preserving the selected checkout projection."""
    identity = repo.identity()
    worktrees = repo.worktrees()
    selected = next((worktree for worktree in worktrees if worktree.path == checkout_path), None)
    if selected is None:
        raise UnsupportedCheckout(f"Select an explicit checkout root; subdirectories and files are unsupported: {checkout_path}")
    if selected.head is None and selected.branch is None:
        raise UnsupportedCheckout(f"No usable working checkout; bare repositories are unsupported: {checkout_path}")
    return RepoInspection(RepoId(identity.key), identity.common_dir, selected.path, identity.origin_url)
