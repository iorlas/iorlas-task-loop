"""Public value records and operation outcomes shared by the real and fake adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NewType, Self

from git_porcelain.diagnostic_output import redact_output

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from pathlib import Path

__all__ = [
    "Aborted",
    "BranchHeld",
    "BranchTaken",
    "Change",
    "CommandResult",
    "Conflict",
    "Diff",
    "Dirty",
    "FinishResult",
    "Health",
    "HookRejected",
    "LogEntry",
    "NothingToRecord",
    "Offline",
    "Pick",
    "PushResult",
    "Pushed",
    "RebaseResult",
    "Rebased",
    "RecordResult",
    "Recorded",
    "Ref",
    "RefEntry",
    "RefRejected",
    "Refs",
    "Rejected",
    "Relation",
    "Released",
    "RemoteRef",
    "RemoteRefs",
    "RemoteRejected",
    "RepoIdentity",
    "Sha",
    "Snapshot",
    "StillHeld",
    "SyncResult",
    "Synced",
    "TakeResult",
    "Transient",
    "Tree",
    "TreeId",
    "UpToDate",
    "WorktreeInfo",
]


class _Output:
    output: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output))


Sha = NewType("Sha", str)
TreeId = NewType("TreeId", str)


# -- facts ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RepoIdentity:
    """Where the repository lives and one stable name for it. ``root`` is the main checkout, ``key`` is
    ``sha1(common_dir)[:12]`` (the same for every worktree)."""

    root: Path
    common_dir: Path
    origin_url: str | None
    key: str


@dataclass(frozen=True)
class Health:
    """Whether a checkout is the repository it claims to be. ``set_in`` is the config file to fix."""

    ok: bool
    problem: Literal["worktree_redirected", "bare", "toplevel_mismatch"] | None
    detail: str
    set_in: Path | None
    worktree_config: bool


@dataclass(frozen=True)
class Snapshot:
    """The work as git would commit it. ``tree`` includes untracked files; ``head_tree`` is the committed tree
    (a gate key, a hook env value). ``base`` is the merge-base of the base ref and HEAD (``base_tip`` when HEAD is
    unborn); ``base_tip`` is the base ref's commit now (a check-cache key)."""

    tree: TreeId
    head: Sha | None
    head_tree: TreeId | None
    branch: str | None
    base: Sha
    base_tip: Sha


@dataclass(frozen=True)
class Change:
    path: str
    kind: Literal["A", "M", "D"]
    added: int
    deleted: int


@dataclass(frozen=True)
class Diff:
    """Between two trees. ``changes == ()`` and ``patch == ""`` mean no change, not an error."""

    changes: tuple[Change, ...]
    patch: str
    truncated: bool


@dataclass(frozen=True)
class Dirty:
    """One status read. Raw dirty is ``tracked or untracked``; meaningful dirty is
    ``tracked or (untracked - base_ignored)``. ``ignored`` lists only ignored files under the asked prefixes."""

    tracked: tuple[str, ...]
    untracked: tuple[str, ...]
    base_ignored: frozenset[str]
    ignored: tuple[str, ...]

    @property
    def raw(self) -> bool:
        return bool(self.tracked or self.untracked)

    @property
    def meaningful(self) -> bool:
        return bool(self.tracked or set(self.untracked) - self.base_ignored)


@dataclass(frozen=True)
class LogEntry:
    """A commit as ``Repo.history`` returns it. ``upstream``: its patch is already on the asked base, else None."""

    sha: Sha
    ts: int
    subject: str
    body: str
    upstream: bool | None


@dataclass(frozen=True)
class Relation:
    """``a`` against ``b``: ``ahead = |b..a|``, ``behind = |a..b|``."""

    merge_base: Sha | None
    ahead: int
    behind: int


@dataclass(frozen=True)
class Pick:
    """One oldest-first git cherry row; upstream means an equivalent patch exists there."""

    oid: Sha
    upstream: bool


@dataclass(frozen=True)
class CommandResult(_Output):
    """Exit status and complete stripped stdout plus stderr; command refusals are data."""

    ok: bool
    output: str


@dataclass(frozen=True)
class RefEntry:
    """A full local ref name and its object id."""

    name: str
    sha: Sha


@dataclass(frozen=True)
class RemoteRef:
    """An advertised ref, including HEAD and peeled tags; names remain fully qualified."""

    name: str
    oid: Sha


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    head: Sha | None
    branch: str | None
    is_main: bool
    dirty: bool | None


class Tree:
    """A commit's (or tree's) files, read lazily. Resolved once at construction; ``files`` lists on first use."""

    def __init__(
        self,
        sha: Sha,
        lister: Callable[[], Mapping[str, tuple[str, Sha]]],
        reader: Callable[[str], bytes | None],
    ) -> None:
        self.sha = sha
        self._lister = lister
        self._reader = reader
        self._files: Mapping[str, tuple[str, Sha]] | None = None
        self._blobs: dict[str, bytes | None] = {}

    @property
    def files(self) -> Mapping[str, tuple[str, Sha]]:
        """Path to ``(mode, blob sha)``."""
        if self._files is None:
            self._files = self._lister()
        return self._files

    def read(self, path: str) -> bytes | None:
        """The bytes of ``path`` here; None when absent."""
        if path not in self._blobs:
            self._blobs[path] = self._reader(path)
        return self._blobs[path]


# -- results of the write operations ----------------------------------------------------------------------
@dataclass(frozen=True)
class Recorded(_Output):
    sha: Sha
    output: str = ""


@dataclass(frozen=True)
class NothingToRecord(_Output):
    output: str = ""


@dataclass(frozen=True)
class HookRejected:
    tail: str
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


@dataclass(frozen=True)
class BranchTaken:
    branch: str
    head: Sha
    created: bool
    kept_aside: str | None


@dataclass(frozen=True)
class BranchHeld:
    holders: tuple[WorktreeInfo, ...]


@dataclass(frozen=True)
class Released:
    path: Path
    how: Literal["removed", "detached"]


@dataclass(frozen=True)
class StillHeld:
    path: Path
    why: str


@dataclass(frozen=True)
class UpToDate(_Output):
    output: str = ""


@dataclass(frozen=True)
class Rebased(_Output):
    old_head: Sha
    new_head: Sha
    squashed: bool
    squash_failure: str | None = None
    output: str = ""


@dataclass(frozen=True)
class Conflict:
    """A rebase stopped on conflicts (or ``finish_rebase("continue")`` found markers left). It stays paused."""

    files: tuple[str, ...]
    tail: str
    old_head: Sha
    squash_failure: str | None = None
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


@dataclass(frozen=True)
class Aborted(_Output):
    head: Sha
    output: str = ""


@dataclass(frozen=True)
class Pushed(_Output):
    sha: Sha
    output: str = ""


@dataclass(frozen=True)
class Rejected:
    tail: str
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


@dataclass(frozen=True)
class RefRejected(Rejected):
    """The destination changed or the update was not a fast-forward."""


@dataclass(frozen=True)
class RemoteRejected:
    """The remote refused an update for policy or another non-race reason."""

    tail: str
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


@dataclass(frozen=True)
class Transient:
    tail: str
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


@dataclass(frozen=True)
class Synced(_Output):
    output: str = ""


@dataclass(frozen=True)
class Offline:
    tail: str
    output: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", redact_output(self.output or self.tail))
        object.__setattr__(self, "tail", redact_output(self.tail)[-600:])


class RemoteRefs(tuple[RemoteRef, ...]):
    """Advertised refs, retaining tuple behavior and complete command diagnostics."""

    output: str

    def __new__(cls, refs: Iterable[RemoteRef] = (), *, output: str = "") -> Self:
        result = super().__new__(cls, refs)
        result.output = redact_output(output)
        return result


RecordResult = Recorded | NothingToRecord | HookRejected
TakeResult = BranchTaken | BranchHeld
RebaseResult = UpToDate | Rebased | Conflict
FinishResult = Rebased | Conflict | Aborted
PushResult = Pushed | Rejected | Transient | HookRejected | RemoteRejected
SyncResult = Synced | Offline


@dataclass(frozen=True)
class Ref:
    """A ref's name and object id; branch listings use names relative to their namespace."""

    name: str
    oid: str


class Refs(list[Ref]):
    """Path-based remote refs with list behavior and complete command output."""

    def __init__(self, refs: Iterable[Ref] = (), *, output: str = "") -> None:
        super().__init__(refs)
        self.output = redact_output(output)
