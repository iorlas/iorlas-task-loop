"""The git seam of a driver that works on checkouts: two protocols, fat intent operations, typed results.

``Repo`` holds what every checkout of a repository shares (identity, history, remote, the worktree list).
``Worktree`` is one checkout: its state and the write arcs a driver takes. ``RealRepo`` (``git_porcelain.real``)
runs the git binary; ``FakeRepo`` (``git_porcelain.testing``) models the same domain state in memory. One
contract suite runs the same scenarios against both, so the fake cannot drift.

Failure has two classes. An expected condition (nothing to commit, a rebase conflict, a rejected push) is a
variant of the result union, ``match``-able. Infrastructure (git missing, ``index.lock`` held, no identity, not
a repository, a timeout, a revision that does not resolve) raises :class:`GitUnavailable`; no operation returns
an empty string for a failure. A precondition the caller must check first (a rebase on a tracked-dirty tree)
raises ``ValueError``: a programming error, not a git outcome.

Nothing git-specific crosses the seam: callers pass shas and plain ref names, and get records back; argv,
exit codes, stderr text, ``GIT_*`` variables and ``.git`` layout stay inside the implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NewType, Protocol

from git_porcelain.errors import GitUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "Aborted",
    "BranchHeld",
    "BranchTaken",
    "Change",
    "Conflict",
    "Diff",
    "Dirty",
    "FinishResult",
    "GitUnavailable",
    "Health",
    "HookRejected",
    "LogEntry",
    "NothingToRecord",
    "Offline",
    "PushResult",
    "Pushed",
    "RebaseResult",
    "Rebased",
    "RecordResult",
    "Recorded",
    "Rejected",
    "Relation",
    "Released",
    "Repo",
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
    "Worktree",
    "WorktreeInfo",
]

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
class Recorded:
    sha: Sha


@dataclass(frozen=True)
class NothingToRecord:
    pass


@dataclass(frozen=True)
class HookRejected:
    tail: str


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
class UpToDate:
    pass


@dataclass(frozen=True)
class Rebased:
    old_head: Sha
    new_head: Sha
    squashed: bool


@dataclass(frozen=True)
class Conflict:
    """A rebase stopped on conflicts (or ``finish_rebase("continue")`` found markers left). It stays paused."""

    files: tuple[str, ...]
    tail: str
    old_head: Sha


@dataclass(frozen=True)
class Aborted:
    head: Sha


@dataclass(frozen=True)
class Pushed:
    sha: Sha


@dataclass(frozen=True)
class Rejected:
    tail: str


@dataclass(frozen=True)
class Transient:
    tail: str


@dataclass(frozen=True)
class Synced:
    pass


@dataclass(frozen=True)
class Offline:
    tail: str


RecordResult = Recorded | NothingToRecord | HookRejected
TakeResult = BranchTaken | BranchHeld
RebaseResult = UpToDate | Rebased | Conflict
FinishResult = Rebased | Conflict | Aborted
PushResult = Pushed | Rejected | Transient | HookRejected
SyncResult = Synced | Offline


# -- the seam ---------------------------------------------------------------------------------------------
class Repo(Protocol):
    """What every checkout of one repository shares."""

    def identity(self) -> RepoIdentity:
        """Root, common dir, origin url and key. Asked once per process."""
        ...

    def sync(self, remote: str = "origin") -> SyncResult:
        """Fetch ``remote``; a lost ref-lock race is retried inside. ``Offline`` when it cannot be reached."""
        ...

    def relate(self, a: str, b: str) -> Relation:
        """Merge base and ahead/behind counts of two revisions, in one look."""
        ...

    def history(
        self,
        revs: Sequence[str],
        *,
        not_on: Sequence[str] = (),
        limit: int | None = None,
        patch_equivalent_to: str | None = None,
    ) -> tuple[LogEntry, ...]:
        """Commits reachable from ``revs`` and not from ``not_on``, newest first. ``patch_equivalent_to`` (one
        rev in ``revs``) sets ``LogEntry.upstream`` by patch id."""
        ...

    def branches(self, prefix: str = "") -> tuple[tuple[str, Sha], ...]:
        """Local branches whose name starts with ``prefix``, sorted, with their tips."""
        ...

    def tree(self, rev: str) -> Tree | None:
        """The tree of a commit-ish or tree id; None when ``rev`` names nothing."""
        ...

    def worktrees(self, *, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        """Every worktree, the main one first; ``dirty`` is filled only with ``with_dirty``."""
        ...

    def add_worktree(self, path: Path, rev: str) -> Worktree:
        """A new linked worktree at ``path``, detached at ``rev``."""
        ...

    def drop_worktree(self, path: Path, *, force: bool = False) -> None:
        """Remove a worktree (a dirty one needs ``force``; one whose folder is gone is only forgotten), then prune."""
        ...

    def exclude_locally(self, patterns: Sequence[str]) -> None:
        """Append the missing ``patterns`` to the repository's ``info/exclude``."""
        ...

    def worktree(self, path: Path) -> Worktree:
        """The checkout at ``path``."""
        ...


class Worktree(Protocol):
    """One checkout: its state and the arcs a driver takes."""

    path: Path

    @property
    def repo(self) -> Repo:
        """The repository this checkout belongs to."""
        ...

    def health(self) -> Health:
        """Is this checkout the repository it claims to be. Never memoized: it exists to catch a stray config."""
        ...

    def snapshot(self, base: str) -> Snapshot:
        """The work as git would commit it (a throwaway index, the real one untouched), plus head, branch and base."""
        ...

    def diff(self, a: str, b: str, *, exclude: Sequence[str] = (), cap: int | None = None) -> Diff:
        """Changes and patch from tree-ish ``a`` to ``b``; ``exclude`` lists literal paths left out; a patch longer
        than ``cap`` characters is cut and ``truncated`` set."""
        ...

    def dirty(self, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        """Tracked and untracked changes in one read. With ``base``, also the untracked paths that base's
        ``.gitignore`` files would ignore; with ``ignored_under``, the ignored files below those prefixes."""
        ...

    def record(
        self,
        message: str,
        *,
        paths: Literal["own", "all"] = "own",
        base: str | None = None,
        mode: Literal["new", "amend", "squash_to"] = "new",
        squash_to: Sha | None = None,
        hooks: bool = False,
        allow_empty: bool = False,
    ) -> RecordResult:
        """Stage and commit. ``own``: tracked changes plus untracked files base's ignore rules do not cover, by
        exact path. ``all``: everything. ``amend`` folds into HEAD (empty ``message`` keeps its message);
        ``squash_to`` first moves HEAD softly to ``squash_to``. Hooks are skipped unless ``hooks``."""
        ...

    def take_branch(
        self,
        branch: str,
        base: str,
        *,
        mode: Literal["resume", "fresh", "restart"],
        keep_aside_as: str | None = None,
        clean_keep: Sequence[str] | None = None,
    ) -> TakeResult:
        """Check out ``branch``. ``resume``: as it is (created at ``base`` when absent). ``fresh``: at ``base``, the
        old tip with work beyond ``base`` kept as ``keep_aside_as``. ``restart``: at ``base``, the old tip dropped.
        ``BranchHeld`` when another worktree holds it. ``clean_keep`` (not None) then deletes untracked files
        except those patterns."""
        ...

    def release_branch(self, holder: Path) -> Released | StillHeld:
        """Free the branch ``holder`` holds: remove a clean linked worktree, else detach it there."""
        ...

    def park(self, base: str, *, clean_keep: Sequence[str] | None = None) -> Sha:
        """Detach HEAD at ``base`` (the branch stays); ``clean_keep`` as in :meth:`take_branch`."""
        ...

    def rebase_onto(self, base: str, *, squash_message: str | None = None) -> RebaseResult:
        """Replay the branch onto ``base``; with ``squash_message``, first squash a branch of more than one commit.
        A conflict leaves the rebase paused. Raises ``ValueError`` on a tracked-dirty tree or a paused rebase."""
        ...

    def finish_rebase(self, action: Literal["continue", "abort"], *, restore_to: Sha | None = None) -> FinishResult:
        """``continue``: stage the files that were conflicted; ``Conflict`` while markers remain, else go on.
        ``abort``: abandon, then ``reset --hard`` to ``restore_to`` when given. A no-op when nothing is paused."""
        ...

    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None) -> PushResult:
        """Push HEAD to branch ``dst`` (never forced). The repository's pre-push hook runs, with ``hook_env`` added."""
        ...

    def landed(self, base: str, title_suffix: str) -> Sha | None:
        """HEAD's sha when its subject ends with ``title_suffix`` and it is already on ``base``."""
        ...

    def grep_tracked(self, term: str) -> tuple[str, ...]:
        """Tracked text files holding ``term`` as a whole word (fixed string)."""
        ...
