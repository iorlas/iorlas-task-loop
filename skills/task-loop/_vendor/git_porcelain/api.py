"""The git seam of a driver that works on checkouts: two protocols, fat intent operations, typed results.

``Repo`` holds what every checkout of a repository shares (identity, history, remote, the worktree list).
``Worktree`` is one checkout: its state and the write arcs a driver takes. ``RealRepo`` (``git_porcelain.real``)
runs the git binary; ``FakeRepo`` (``git_porcelain.testing``) models the same domain state in memory. One
contract suite runs the same scenarios against both, so the fake cannot drift.

Failure has two classes. An expected condition (nothing to commit, a rebase conflict, a rejected push) is a
variant of the result union, ``match``-able; worktree removal instead raises ``WorktreeRemoveRefused``.
Infrastructure (git missing, ``index.lock`` held, no identity, not
a repository, a timeout, a revision that does not resolve) raises :class:`GitUnavailable`; no operation returns
an empty string for a failure. A precondition the caller must check first (a rebase on a tracked-dirty tree)
raises ``ValueError``: a programming error, not a git outcome.

Callers pass shas and plain ref names and get records back; argv, exit codes, ``GIT_*`` variables and ``.git``
layout stay inside the implementations. ``worktree_state`` deliberately exposes porcelain bytes for signatures;
``WorktreeRemoveRefused.reason`` exposes the diagnostic a caller can show when removal is refused.
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
    "CommandResult",
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
    "Pick",
    "PushResult",
    "Pushed",
    "RebaseResult",
    "Rebased",
    "RecordResult",
    "Recorded",
    "RefRejected",
    "Rejected",
    "Relation",
    "Released",
    "RemoteRejected",
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
class Pick:
    """One oldest-first git cherry row; upstream means an equivalent patch exists there."""

    oid: Sha
    upstream: bool


@dataclass(frozen=True)
class CommandResult:
    """Exit status and complete stripped stdout plus stderr; command refusals are data."""

    ok: bool
    output: str


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
    squash_failure: str | None = None


@dataclass(frozen=True)
class Conflict:
    """A rebase stopped on conflicts (or ``finish_rebase("continue")`` found markers left). It stays paused."""

    files: tuple[str, ...]
    tail: str
    old_head: Sha
    squash_failure: str | None = None


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
class RefRejected(Rejected):
    """The destination changed or the update was not a fast-forward."""


@dataclass(frozen=True)
class RemoteRejected:
    """The remote refused an update for policy or another non-race reason."""

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
PushResult = Pushed | Rejected | Transient | HookRejected | RemoteRejected
SyncResult = Synced | Offline


# -- the seam ---------------------------------------------------------------------------------------------
class Repo(Protocol):
    """What every checkout of one repository shares."""

    def merge_base(self, a: str, b: str) -> Sha | None:
        """None only for missing revisions or unrelated histories; observation faults raise GitReadFailure."""
        ...

    def cherry(self, upstream: str, head: str) -> tuple[Pick, ...]:
        """Non-merge picks in git cherry order with patch equivalence."""
        ...

    def remote_url(self, remote: str) -> str:
        """Expanded fetch URL; MissingRemote only for a missing named remote."""
        ...

    def fetch(self, remote: str = "origin", *, refspecs: Sequence[str] = (), timeout: float | None = None) -> None:
        """Fetch named remote or source URL/path, writing FETCH_HEAD; retry ref-lock races five times."""
        ...

    def delete_remote_at(self, remote: str, ref: str, expected: Sha) -> None:
        """Lease-guarded deletion of a full refs/ name; authoritative absence also succeeds after refusal."""
        ...

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
        base) sets ``LogEntry.upstream`` by patch id."""
        ...

    def branches(self, prefix: str = "") -> tuple[tuple[str, Sha], ...]:
        """Local branches whose name starts with ``prefix``, sorted, with their tips."""
        ...

    def rename_branch(self, old: str, new: str) -> None:
        """Rename a local branch without replacing an existing branch."""
        ...

    def delete_branch(self, branch: str, *, expected: Sha) -> None:
        """Delete only at ``expected``; checked out raises ``BranchPinned``, stale tip non-retryable ``RefRace``."""
        ...

    def tree(self, rev: str) -> Tree | None:
        """The tree of a commit-ish or tree id; None when ``rev`` names nothing."""
        ...

    def worktrees(self, *, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        """Every worktree, the main one first; ``dirty`` is filled only with ``with_dirty``."""
        ...

    def add_worktree(self, path: Path, rev: str, *, force: bool = False) -> Worktree:
        """A linked worktree detached at ``rev``; ``force`` permits a registered but missing checkout."""
        ...

    def drop_worktree(self, path: Path, *, force: bool = False, missing_ok: bool = True) -> None:
        """Remove a worktree, raising ``WorktreeRemoveRefused`` with git's reason on refusal.
        By default absent folders are accepted and registrations pruned. ``missing_ok=False``
        requires a registered linked worktree and never prunes other registrations."""
        ...

    def prune_worktrees(self) -> None:
        """Prune stale worktree registrations without removing live checkouts."""
        ...

    def worktree_state(self, path: Path) -> bytes | None:
        """Raw ``--no-optional-locks status --porcelain=v2 --branch -z --untracked-files=all``.
        Never memoized; None when the path is not a worktree."""
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

    def branch(self) -> str | None:
        """Symbolic HEAD's short branch name, including unborn branches; None when detached."""
        ...

    def checkout(self, ref: str) -> None:
        """Check out an existing branch or commit-ish, preserving compatible local edits."""
        ...

    def checkout_new(self, branch: str, start: str = "HEAD") -> None:
        """Create and check out a branch exclusively; ``BranchExists`` if already present."""
        ...

    def clean(self, keep: Sequence[str] = (), *, ignored: bool = False) -> None:
        """Remove untracked files except keep patterns; optionally remove ignored files too."""
        ...

    def reset(self, rev: str, *, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        """Move HEAD; mixed also resets the index, hard also discards tracked file edits."""
        ...

    def checkout_force(self, branch: str, start: str) -> None:
        """Create or reset a branch at start and check it out, discarding local changes."""
        ...

    @property
    def repo(self) -> Repo:
        """The repository this checkout belongs to."""
        ...

    def health(self) -> Health:
        """Is this checkout the repository it claims to be. Never memoized: it exists to catch a stray config."""
        ...

    def snapshot(self, base: str, *, inputs: Sequence[str] = ()) -> Snapshot:
        """The work as git would commit it, plus head, branch and base. ``inputs`` are literal
        paths (files or directories) included even when ignored; the real index is untouched."""
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
        paths: Literal["own", "all", "tracked", "staged"] = "own",
        base: str | None = None,
        mode: Literal["new", "amend", "squash_to"] = "new",
        squash_to: Sha | None = None,
        hooks: bool = False,
        allow_empty: bool = False,
    ) -> RecordResult:
        """Stage and commit. ``own``: tracked changes plus untracked files base's ignore rules do not cover, by
        exact path. ``all``: everything. ``tracked``: index-tracked changes, including staged additions,
        without untracked files. ``staged``: commit the existing index without staging working files.
        ``amend`` folds into HEAD (empty ``message`` keeps its message), even without staged changes;
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

    def rebase_onto(
        self,
        base: str,
        *,
        squash_message: str | None = None,
        squash_failure: Literal["raise", "continue_unsquashed"] = "raise",
        update_refs: bool | None = None,
    ) -> RebaseResult:
        """Replay the branch onto ``base``; with ``squash_message``, first squash a branch of more than one commit.
        A conflict leaves the rebase paused. Raises ``ValueError`` on a tracked-dirty tree or a paused rebase."""
        ...

    def rebase(self, base: str, *, update_refs: bool | None = None) -> CommandResult:
        """Invoke rebase even when up to date; preserve every git refusal and diagnostic."""
        ...

    def continue_rebase(self, *, stage_conflicts: bool = False, check_markers: bool = False, missing_ok: bool = False) -> CommandResult:
        """Continue using the existing index unless staging is explicitly requested."""
        ...

    def abort_rebase(self, *, missing_ok: bool = True, restore_to: Sha | None = None) -> CommandResult:
        """Abort, optionally restoring HEAD; missing_ok permits no paused rebase, even unborn."""
        ...

    def rebasing(self) -> bool:
        """Observe both rebase backends in this checkout's git directory."""
        ...

    def unmerged(self) -> tuple[str, ...]:
        """Fresh NUL-safe unmerged paths in git order; observation faults raise GitReadFailure."""
        ...

    def push_request(
        self,
        remote: str | None,
        refspecs: Sequence[str],
        *,
        options: Sequence[str] = (),
        force: bool = False,
        allow_delete: bool = False,
        hook_env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Push supplied forms and options; force/deletion need explicit opt ins. Pin HEAD before hooks."""
        ...

    def push_refspecs(
        self,
        remote: str,
        refspecs: Sequence[str],
        *,
        force: bool = False,
        allow_delete: bool = False,
        hook_env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> PushResult:
        """Push explicit refs with opt ins for force/deletion; deletion-only success has an empty sha."""
        ...

    def push_lease(self, remote: str, refspec: str, *, timeout: float = 3600) -> CommandResult:
        """Push with plain force-with-lease and normal hooks, without changing upstream config."""
        ...

    def lfs_push(self, remote: str, refs: Sequence[str], *, timeout: float = 3600) -> CommandResult:
        """Upload all requested refs in one invocation without installing LFS or hooks."""
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
