"""git-porcelain's own error types — no dependency on any host's error taxonomy.

The host translates :class:`GitError` into its own error type at the seam (a2kay
maps it to its typed ``GitError`` for the error dispatcher). :class:`GitUnavailable` is what the
``Repo``/``Worktree`` protocols raise for infrastructure (git missing, a held ``index.lock``, no identity,
not a repository, a timeout). ``WorktreeRemoveRefused`` also inherits it for compatibility with callers
already catching removal failures, and carries the expected refusal's diagnostic separately.
"""

from __future__ import annotations

import re


class GitError(Exception):
    """A git invocation failed. ``retryable`` marks transient failures; ``hint`` is optional."""

    def __init__(self, message: str, *, retryable: bool = False, hint: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.hint = hint


class GitUnavailable(GitError):
    """Git could not answer: ``tail`` is the end of its output, ``retryable`` says a later try may succeed."""

    @property
    def tail(self) -> str:
        return str(self)


class MissingRevision(GitUnavailable):
    """A revision does not identify a git object."""


class NotARepo(GitUnavailable):
    """The requested path is outside a repository or does not exist."""


class WorktreeRemoveRefused(GitUnavailable):
    """Removal was refused; ``reason`` is the final nonempty line of git's stderr."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IndexLocked(GitUnavailable):
    """Another writer holds the index lock."""


class RefRace(GitUnavailable):
    """A ref changed since it was read, or another writer holds its lock."""


class BranchPinned(GitUnavailable):
    """Another worktree has the branch checked out; ``holder`` names it."""

    def __init__(self, message: str, holder: str, *, retryable: bool = False, hint: str | None = None) -> None:
        super().__init__(message, retryable=retryable, hint=hint)
        self.holder = holder


_INDEX_LOCK = re.compile(r"index\.lock")
_REF_STALE = re.compile(r"incorrect old value|is at \S+ but expected \S+")
_REF_LOCK = re.compile(r"cannot lock ref[^\n]*\.lock|Unable to create '[^']*\.lock'")
_REF_RACE = re.compile(r"cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
_PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
_MISSING_REVISION = re.compile(r"fatal: (?:bad revision '.+'|Not a valid object name .+)")
_AMBIGUOUS_REVISION = re.compile(r"fatal: ambiguous argument '.+': unknown revision or path not in the working tree\.")


def failure(message: str, stderr: str, code: int, *, retryable: bool = False, hint: str | None = None) -> GitUnavailable:
    """Translate git's specific diagnostics; an unknown failure remains ``GitUnavailable``."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    tail = next((line for line in lines if line.startswith(("fatal:", "error:"))), lines[-1] if lines else "")
    kind: type[GitUnavailable] = GitUnavailable
    if _INDEX_LOCK.search(stderr):
        kind, retryable = IndexLocked, True
    elif match := _PINNED.search(stderr):
        return BranchPinned(message, match.group(1).strip(), hint=hint)
    elif _REF_STALE.search(stderr) or _REF_RACE.search(stderr):
        kind = RefRace
        retryable = _REF_LOCK.search(stderr) is not None and _REF_STALE.search(stderr) is None
    elif code == 128:
        if (
            tail == "fatal: not a git repository (or any of the parent directories): .git"
            or re.fullmatch(r"fatal: cannot change to '.+': No such file or directory", tail)
            or tail.startswith("fatal: not a git repository:")
        ):
            kind = NotARepo
        elif _MISSING_REVISION.fullmatch(tail) or _AMBIGUOUS_REVISION.fullmatch(tail):
            kind = MissingRevision
    # merge reports this separately from the revision-reader diagnostics above.
    if re.search(r"merge: .+ - not something we can merge", stderr):
        kind = MissingRevision
    return kind(message, retryable=retryable, hint=hint)


__all__ = [
    "BranchPinned",
    "GitError",
    "GitUnavailable",
    "IndexLocked",
    "MissingRevision",
    "NotARepo",
    "RefRace",
    "WorktreeRemoveRefused",
    "failure",
    "some",
]


def some[T](value: T | None) -> T:
    """Narrow a value git or the model must have; its absence is an internal failure."""
    if value is None:
        msg = "internal: an expected value is missing"
        raise GitUnavailable(msg)
    return value
