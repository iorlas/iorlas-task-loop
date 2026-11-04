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

from typing import TYPE_CHECKING, Literal, Protocol

from git_porcelain.api_results import (
    Aborted,
    BranchHeld,
    BranchTaken,
    Change,
    CommandResult,
    Conflict,
    Diff,
    Dirty,
    FinishResult,
    Health,
    HookRejected,
    LogEntry,
    NothingToRecord,
    Offline,
    Pick,
    Pushed,
    PushResult,
    Rebased,
    RebaseResult,
    Recorded,
    RecordResult,
    Ref,
    RefEntry,
    RefRejected,
    Refs,
    Rejected,
    Relation,
    Released,
    RemoteRef,
    RemoteRefs,
    RemoteRejected,
    RepoIdentity,
    Sha,
    Snapshot,
    StillHeld,
    Synced,
    SyncResult,
    TakeResult,
    Transient,
    Tree,
    TreeId,
    UpToDate,
    WorktreeInfo,
)
from git_porcelain.errors import GitUnavailable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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


# -- the seam ---------------------------------------------------------------------------------------------
class Repo(Protocol):
    """What every checkout of one repository shares."""

    def tag(self, name: str, rev: str) -> None:
        """Create a lightweight tag; TagExists for an existing tag, MissingRevision for an absent object."""
        ...

    def count(self, include: Sequence[str], exclude: Sequence[str] = ()) -> int:
        """Count reachable commits minus exclusions; empty include is zero, absent revisions raise MissingRevision."""
        ...

    def refs(self, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
        """Sorted for-each-ref rows for arbitrary prefixes; empty prefixes select all. Failures raise GitUnavailable."""
        ...

    def ls_remote(self, remote: str, patterns: Sequence[str] = ()) -> RemoteRefs:
        """Advertise remote refs with tail globs and injected environment; transport failures raise GitUnavailable."""
        ...

    def is_ancestor(self, a: str, b: str) -> bool:
        """Whether a is reachable from b; missing revisions raise MissingRevision, faults raise GitReadFailure.

        Leading-dash revisions raise ValueError before invoking git.
        """
        ...

    def merge_base(self, a: str, b: str) -> Sha | None:
        """None only for missing revisions or unrelated histories; observation faults raise GitReadFailure.

        Leading-dash revisions raise ValueError before invoking git.
        """
        ...

    def cherry(self, upstream: str, head: str) -> tuple[Pick, ...]:
        """Non-merge picks in git cherry order with patch equivalence."""
        ...

    def remote_url(self, remote: str) -> str:
        """Expanded fetch URL; MissingRemote only for a missing named remote."""
        ...

    def fetch(self, remote: str = "origin", *, refspecs: Sequence[str] = (), timeout: float | None = None) -> CommandResult:
        """Fetch with bounded ref-race retries, writing FETCH_HEAD; raise on final refusal."""
        ...

    def delete_remote_at(self, remote: str, ref: str, expected: Sha, *, missing_ok: bool = True) -> CommandResult:
        """Lease-guarded deletion; missing_ok=False avoids the verification call after refusal."""
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

    def stage(self, paths: Sequence[str], *, literal: bool = True) -> None:
        """Stage additions, edits and deletions via NUL-delimited pathspecs; git refusals raise GitUnavailable."""
        ...

    def stage_tracked(self) -> None:
        """Stage index-tracked edits/deletions (add -u); failures raise GitUnavailable."""
        ...

    def merge_ff(self, rev: str) -> None:
        """Fast-forward only; NotFastForward for divergence, MissingRevision for absence, DirtyTree for overwrite."""
        ...

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
        ``squash_to`` first moves HEAD softly to ``squash_to``. Hooks are skipped unless ``hooks``.
        Results retain complete combined command output; infrastructure exceptions carry ``output`` too.
        Marker text is not a precondition: git decides whether the index can commit."""
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
        """Resolve base to a commit OID, then invoke rebase even when up to date.

        Leading-dash bases raise ValueError; absent bases raise MissingRevision.
        Preserve every git rebase refusal and diagnostic.
        """
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
        """Push supplied forms and options once; force/deletion need explicit opt ins. Git resolves HEAD."""
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

    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None, head: Sha | None = None) -> PushResult:
        """Push HEAD or caller-supplied full ``head`` to ``dst``; supplying it avoids a resolution process."""
        ...

    def landed(self, base: str, title_suffix: str) -> Sha | None:
        """HEAD's sha when its subject ends with ``title_suffix`` and it is already on ``base``."""
        ...

    def grep_tracked(self, term: str) -> tuple[str, ...]:
        """Tracked text files holding ``term`` as a whole word (fixed string)."""
        ...
