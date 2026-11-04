"""Checkout integration using git's fast-forward and rebase policies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.porcelain import run_git
from git_porcelain.revision_validation import validate_revisions

if TYPE_CHECKING:
    from pathlib import Path


def merge_ff(repo: Path, ref: str) -> None:
    """Fast-forward to ``ref``; refuse divergence or an overwrite of local changes."""
    validate_revisions(ref)
    run_git(repo, "merge", "--ff-only", "--", ref, env={"LC_ALL": "C", "LANG": "C"})


def pull_rebase(repo: Path, remote: str, branch: str) -> None:
    """Fetch the named remote branch and replay local commits; conflicts remain for resolution."""
    run_git(repo, "pull", "--rebase", "--", remote, branch)
