"""Translate vendored worktree-pool failures into the task-loop Git port's errors."""

import re
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import override

from git_porcelain import errors
from git_porcelain.real import Done, RealRepo

from taskloop.adapters.git_base import NOT_A_REPO, classify, error_line
from tlkernel.slots import (
    BranchPinned,
    DirtyTree,
    GitReadFailure,
    IndexLocked,
    MissingRemote,
    MissingRevision,
    NotARepo,
    NotAWorktree,
    RefRace,
    SlotGitError,
)


class UnpinnedRepo(RealRepo):
    """Keep the port's explicit ambient-checkout mode across pool operations."""

    @override
    def run(self, cwd: Path, *args: str, check: bool = True, pin: bool = True, stdin: str | None = None,
            env: Mapping[str, str] | None = None, timeout: float | None = None) -> Done:
        return super().run(cwd, *args, check=check, pin=False, stdin=stdin, env=env, timeout=timeout)


def pool_read_error(error: errors.GitError) -> GitReadFailure:
    """Unknown reads stay faults, while typed absence keeps its port subtype."""
    translated = pool_error(error)
    kind = type(translated) if isinstance(translated, GitReadFailure) else GitReadFailure
    if "fatal: this operation must be run in a work tree" in str(error):
        kind = NotAWorktree
    if isinstance(error, errors.MissingRemote):
        kind = MissingRemote
    return kind(str(error))


def pool_error(error: errors.GitError) -> SlotGitError:
    """Preserve typed failures and the branch holder across the porcelain boundary."""
    # Writes historically exposed git's diagnostic without the runner's exit-status envelope.
    message = re.sub(r"^git \S+ exited \d+: ", "", str(error))
    if isinstance(error, errors.BranchPinned):
        held = BranchPinned(error_line(message), error.holder)
        held.output = message
        return held
    kinds: tuple[tuple[type[errors.GitError], type[SlotGitError]], ...] = (
        (errors.MissingRevision, MissingRevision),
        (errors.NotARepo, NotARepo),
        (errors.DirtyTree, DirtyTree),
        (errors.IndexLocked, IndexLocked),
        (errors.RefRace, RefRace),
    )
    for source, target in kinds:
        if isinstance(error, source):
            return target(error_line(message), output=message)
    # Retain the port's classifier for otherwise untyped diagnostics.
    translated = NotARepo(error_line(message)) if NOT_A_REPO.fullmatch(error_line(message)) else classify(message)
    translated.output = message
    return translated


def remote_error(error: errors.GitError, *, push: bool = False) -> SlotGitError:
    """A remote call's failure keeps git's complete words: `output` is all of them, `tail` the line that says why."""
    full = getattr(error, "output", None) or str(error)
    if isinstance(error, errors.GitReadFailure):
        translated: SlotGitError = GitReadFailure(str(error))
    else:
        translated = classify(full, push=push)
    translated.output = full
    return translated


@contextmanager
def pool_errors(translate: Callable[[errors.GitError], Exception] = pool_error) -> Generator[None]:
    """Run porcelain calls in the block; a failure leaves as the port's error (`pool_read_error` for reads)."""
    try:
        yield
    except errors.GitError as err:
        raise translate(err) from err
