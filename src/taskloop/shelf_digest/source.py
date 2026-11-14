"""The digest's committed-source adapter over the owning Git API."""

from dataclasses import dataclass
from enum import StrEnum

from git_porcelain import GitUnavailable, Repo, Tree


class ReadFailureReason(StrEnum):
    NO_COMMIT = "no_commit"
    NO_PATH = "no_path"
    NOT_A_FILE = "not_a_file"
    UNREADABLE = "unreadable"
    UNAVAILABLE = "unavailable"
    INVALID_PATH = "invalid_path"


@dataclass(frozen=True)
class ReadFailure:
    reason: ReadFailureReason
    explanation: str


@dataclass(frozen=True)
class SourceEntry:
    path: str
    mode: str
    object_id: str


def relative_path(path: str) -> bool:
    """Require an unambiguous, package-relative object path, without filesystem traversal."""
    return (
        bool(path) and "\\" not in path and not any(ord(char) < 32 or ord(char) == 127 for char in path)
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


@dataclass(frozen=True)
class CommittedSource:
    commit: str
    _tree: Tree

    def entries(self) -> tuple[SourceEntry, ...] | ReadFailure:
        """List the resolved tree, retaining modes and object identities."""
        try:
            return tuple(SourceEntry(path, mode, str(sha)) for path, (mode, sha) in sorted(self._tree.files.items()))
        except GitUnavailable as error:
            return ReadFailure(ReadFailureReason.UNAVAILABLE, f"Cannot list source at {self.commit}: {error}")

    def read(self, path: str) -> bytes | ReadFailure:
        """Read only regular committed files; a listed but unreadable object is never absent."""
        location = f"{path} at {self.commit}"
        if not relative_path(path):
            return ReadFailure(ReadFailureReason.INVALID_PATH, f"Invalid relative source path: {location}")
        try:
            entry = self._tree.files.get(path)
            if entry is None:
                return ReadFailure(ReadFailureReason.NO_PATH, f"No source path {location}")
            if entry[0] not in {"100644", "100755"}:
                return ReadFailure(ReadFailureReason.NOT_A_FILE, f"{location} is not a regular file (mode {entry[0]})")
            data = self._tree.read(path)
        except GitUnavailable as error:
            return ReadFailure(ReadFailureReason.UNAVAILABLE, f"Cannot read {location}: {error}")
        if data is None:
            return ReadFailure(ReadFailureReason.UNREADABLE, f"{location} is listed but its object cannot be read")
        return data


def open_source(repo: Repo, revision: str) -> CommittedSource | ReadFailure:
    """Resolve once to a commit, never consulting a checkout file or fetching a missing object."""
    try:
        try:
            tree = repo.tree(f"{revision}^{{commit}}")
        except ValueError:
            return ReadFailure(ReadFailureReason.NO_COMMIT, f"Invalid source revision {revision!r}")
        if tree is None:
            repo.identity()  # Repository failure must not masquerade as an absent commit.
            return ReadFailure(ReadFailureReason.NO_COMMIT, f"No source commit for {revision!r}")
        return CommittedSource(str(tree.sha), tree)
    except GitUnavailable as error:
        return ReadFailure(ReadFailureReason.UNAVAILABLE, f"Cannot open source revision {revision!r}: {error}")
