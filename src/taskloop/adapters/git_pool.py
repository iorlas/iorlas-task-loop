"""Translate vendored worktree-pool failures into the task-loop Git port's errors."""

from collections.abc import Mapping
from pathlib import Path
from typing import override

from git_porcelain import errors
from git_porcelain.real import Done, RealRepo

from taskloop.adapters.git_base import classify
from taskloop.contracts.slots import BranchPinned, GitReadFailure, IndexLocked, MissingRevision, NotARepo, RefRace, SlotGitError


class UnpinnedRepo(RealRepo):
    """Keep the port's explicit ambient-checkout mode across pool operations."""

    @override
    def run(self, cwd: Path, *args: str, check: bool = True, pin: bool = True, stdin: str | None = None,
            env: Mapping[str, str] | None = None, timeout: float | None = None) -> Done:
        return super().run(cwd, *args, check=check, pin=False, stdin=stdin, env=env, timeout=timeout)


def pool_read_error(error: errors.GitError) -> GitReadFailure:
    """Unknown reads stay faults, while typed absence keeps its port subtype."""
    translated = pool_error(error)
    return translated if isinstance(translated, GitReadFailure) else GitReadFailure(str(error))


def pool_error(error: errors.GitError) -> SlotGitError:
    """Preserve typed failures and the branch holder across the porcelain boundary."""
    message = str(error)
    if isinstance(error, errors.BranchPinned):
        return BranchPinned(message, error.holder)
    kinds: tuple[tuple[type[errors.GitError], type[SlotGitError]], ...] = (
        (errors.MissingRevision, MissingRevision),
        (errors.NotARepo, NotARepo),
        (errors.IndexLocked, IndexLocked),
        (errors.RefRace, RefRace),
    )
    for source, target in kinds:
        if isinstance(error, source):
            return target(message)
    # Porcelain has no DirtyTree subtype; retain the port's classifier for otherwise untyped diagnostics.
    return classify(message)
