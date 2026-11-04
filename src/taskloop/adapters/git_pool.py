"""Translate vendored worktree-pool failures into the task-loop Git port's errors."""

from git_porcelain import errors

from taskloop.adapters.git_base import classify
from taskloop.contracts.slots import BranchPinned, IndexLocked, MissingRevision, NotARepo, RefRace, SlotGitError


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
