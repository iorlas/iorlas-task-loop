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
    """Git could not answer: ``output`` retains command diagnostics, ``retryable`` permits a later try.

    ``tail`` remains the exception's display text; invocation failures have only their failure message.
    """

    def __init__(self, message: str, *, retryable: bool = False, hint: str | None = None, output: str | None = None) -> None:
        super().__init__(message, retryable=retryable, hint=hint)
        self.output = message if output is None else output

    @property
    def tail(self) -> str:
        return str(self)


class MissingRevision(GitUnavailable):
    """A revision does not identify a git object."""


class MissingRemote(GitUnavailable):
    """The requested named remote is not configured."""


class GitReadFailure(GitUnavailable):
    """An observation failed; absence cannot be inferred."""


class GitTimeout(GitUnavailable):
    """The child exceeded its deadline; distinct from a failure to invoke it."""


class DirtyTree(GitUnavailable):
    """Local changes would be overwritten by the requested operation."""


class BranchExists(GitUnavailable):
    """Exclusive branch creation or rename found an existing destination."""


class TagExists(GitUnavailable):
    """Exclusive lightweight tag creation found an existing tag."""


class NotFastForward(GitUnavailable):
    """The requested merge would require a merge commit."""


class NotARepo(GitUnavailable):
    """The requested path is outside a repository or does not exist."""


class WorktreeRemoveRefused(GitUnavailable):
    """Removal was refused; ``reason`` is git's first diagnostic (or final nonempty line)."""

    def __init__(self, reason: str, *, code: int = 128, hint_line: str | None = None) -> None:
        message = f"git worktree remove exited {code}: {reason}"
        if hint_line and hint_line != reason:
            message += " | " + hint_line
        super().__init__(message)
        self.reason = reason


class IndexLocked(GitUnavailable):
    """Another writer holds the index lock."""


class RefRace(GitUnavailable):
    """A ref changed since it was read, or another writer holds its lock."""


class BranchPinned(GitUnavailable):
    """A worktree has the branch checked out; ``holder`` names it."""

    def __init__(self, message: str, holder: str, *, retryable: bool = False, hint: str | None = None, output: str | None = None) -> None:
        super().__init__(message, retryable=retryable, hint=hint, output=output)
        self.holder = holder


_INDEX_LOCK = re.compile(r"index\.lock")
_REF_STALE = re.compile(r"incorrect old value|is at \S+ but expected \S+")
_REF_LOCK = re.compile(r"(?:cannot lock ref[^\n]*\.lock|Unable to create '[^'\n]*\.lock')[^\n]*File exists")
_REF_RACE = re.compile(r"cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
_PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
_MISSING_REVISION = re.compile(r"fatal: (?:bad revision '.+'|Not a valid object name .+)")
_AMBIGUOUS_REVISION = re.compile(r"fatal: ambiguous argument '.+': unknown revision or path not in the working tree\.")


def operation_failure(stderr: str) -> type[GitUnavailable]:
    """Operation-specific refusals before the shared infrastructure classification."""
    if re.search(r"tag '.+' already exists", stderr):
        return TagExists
    if "Not possible to fast-forward" in stderr:
        return NotFastForward
    return GitUnavailable


def failure(
    message: str, stderr: str, code: int, *, retryable: bool = False, hint: str | None = None, output: str | None = None
) -> GitUnavailable:
    """Translate git's specific diagnostics; an unknown failure remains ``GitUnavailable``."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    tail = next((line for line in lines if line.startswith(("fatal:", "error:"))), lines[-1] if lines else "")
    kind = operation_failure(stderr)
    if _INDEX_LOCK.search(stderr):
        kind, retryable = IndexLocked, True
    elif match := _PINNED.search(stderr):
        return BranchPinned(message, match.group(1).strip(), hint=hint, output=output)
    elif re.search(r"(?:local changes|untracked working tree files)[\s\S]*would be overwritten|would be overwritten by checkout", stderr):
        kind = DirtyTree
    elif re.search(r"(?:a branch named|a branch) '.+' already exists", stderr, re.IGNORECASE):
        kind = BranchExists
    elif re.search(r"fatal: no branch named '.+'\.?", stderr, re.IGNORECASE):
        kind = MissingRevision
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
    return kind(message, retryable=retryable, hint=hint, output=output)


__all__ = [
    "BranchExists",
    "BranchPinned",
    "DirtyTree",
    "GitError",
    "GitReadFailure",
    "GitTimeout",
    "GitUnavailable",
    "IndexLocked",
    "MissingRemote",
    "MissingRevision",
    "NotARepo",
    "NotFastForward",
    "RefRace",
    "TagExists",
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
