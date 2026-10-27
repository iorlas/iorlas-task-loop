"""git-porcelain's own error types — no dependency on any host's error taxonomy.

The host translates :class:`GitError` into its own error type at the seam (a2kay
maps it to its typed ``GitError`` for the error dispatcher). :class:`GitUnavailable` is what the
``Repo``/``Worktree`` protocols raise: infrastructure only (git missing, a held ``index.lock``, no identity,
not a repository, a timeout), never an expected outcome.
"""

from __future__ import annotations

from typing import TypeVar


class GitError(Exception):
    """A git invocation failed. ``retryable`` marks transient failures; ``hint`` is optional."""

    def __init__(self, message: str, *, retryable: bool = False, hint: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.hint = hint


class GitUnavailable(GitError):  # noqa: N818 — the name the design gives the infrastructure failure
    """Git could not answer: ``tail`` is the end of its output, ``retryable`` says a later try may succeed."""

    @property
    def tail(self) -> str:
        return str(self)


__all__ = ["GitError", "GitUnavailable", "some"]


_T = TypeVar("_T")


def some(value: _T | None) -> _T:
    """Narrow a value git or the model must have; its absence is an internal failure."""
    if value is None:
        msg = "internal: an expected value is missing"
        raise GitUnavailable(msg)
    return value
