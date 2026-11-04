"""``FakeRepo`` and ``FakeWorktree``: the :class:`~git_porcelain.api.Repo` / ``Worktree`` protocols held in memory.

No subprocess, no disk. The domain state is modelled: commits, trees and blobs (hashed the way git hashes them, so
``Snapshot.tree`` equals the real one), refs (``heads/``, ``remotes/``), per-worktree head, index and files,
``info/exclude`` and the root ``.gitignore``, remotes as :class:`FakeRemote` repositories, a paused rebase with its
conflicted files, and config (``core.worktree``, ``core.bare``, ``extensions.worktreeConfig``).

``tests/features/git_contract.feature`` runs the same scenarios against this and against ``RealRepo``. What is not
modelled (each gap is a scenario tagged ``@real-only``, or an absence the README states): rename detection in a diff
(``Change.kind`` is never ``R``); a ``.gitignore`` below the root (base rules given to ``dirty(base)`` are the one
exception) and gitignore beyond globs, ``**``, anchoring, folder-only and negation; conflicts are per file and
per overlapping hunk, not git's line-level merge; no hook runs (knobs only); no LFS; no author, committer or signing; no
reflog, no packed refs, no ``index.lock`` race except by knob; paths are virtual, so ``toplevel_mismatch`` is only
by knob; ``grep_tracked`` is substring-on-word over text blobs; no quotepath, no submodules.

Arranging a test: ``FakeRepo.init`` / ``clone`` make a repository; on the worktree, ``write_file`` / ``remove_file``
play the editor and ``write_markers`` a worker that left conflict markers; on the repo, ``set_config``,
``add_remote``, ``hooks`` (``refuse_commit``, ``refuse_push``, ``push_requires_env``) and ``drop_checkout``; on a
:class:`FakeRemote`, ``advance`` (the base moved) and ``offline``; on a worktree, ``redirect_toplevel`` and ``lock_index``.
"""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Literal, Self

from git_porcelain import fake_checkout as checkout_ops
from git_porcelain import fake_commands, fake_operations, fake_remote
from git_porcelain import fake_flow as flow
from git_porcelain import fake_read as read
from git_porcelain import fake_write as write
from git_porcelain.api import CommandResult, Sha
from git_porcelain.errors import GitReadFailure, GitUnavailable, MissingRevision, NotARepo
from git_porcelain.fake_diff import grep_files
from git_porcelain.fake_ops import branch_ref, clean, hard_to
from git_porcelain.fake_plumbing import FakePlumbing
from git_porcelain.fake_store import CheckoutState, Hooks, RepoState
from git_porcelain.fake_worktrees import worktree_state
from git_porcelain.revision_validation import validate_revisions

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.api import (
        Diff,
        Dirty,
        FinishResult,
        Health,
        LogEntry,
        Pick,
        PushResult,
        RebaseResult,
        RecordResult,
        RefEntry,
        Relation,
        Released,
        RemoteRef,
        RepoIdentity,
        Snapshot,
        StillHeld,
        SyncResult,
        TakeResult,
        Tree,
        WorktreeInfo,
    )

__all__ = ["FakeRemote", "FakeRepo", "FakeWorktree"]


class FakeRemote:
    """A bare repository a :class:`FakeRepo` can fetch from and push to."""

    def __init__(self, url: str, *, default_branch: str = "main") -> None:
        self.url = url
        self.default_branch = default_branch
        self.state = RepoState(common=Path(url), default_branch=default_branch)

    @property
    def offline(self) -> bool:
        return self.state.offline

    @offline.setter
    def offline(self, value: bool) -> None:
        self.state.offline = value

    def branches(self) -> dict[str, str]:
        """Branch name to commit sha."""
        return {r.removeprefix("refs/heads/"): s for r, s in self.state.refs.items() if r.startswith("refs/heads/")}

    def advance(self, branch: str, files: Mapping[str, str | None], message: str = "advance") -> str:
        """Someone else pushed: a new commit on ``branch`` writing ``files`` (None deletes a path). Returns its sha."""
        ref = branch_ref(branch)
        tip = self.state.refs.get(ref)
        tree = dict(self.state.store.commits[tip].files) if tip else {}
        for path, text in files.items():
            if text is None:
                tree.pop(path, None)
            else:
                tree[path] = self.state.store.put_blob(text.encode())
        made = self.state.store.put_commit(tree, (tip,) if tip else (), message, self.state.tick())
        self.state.refs[ref] = made.sha
        return made.sha


class FakeRepo:
    """An in-memory repository; ``path`` is any of its checkouts."""

    def __init__(self, state: RepoState, path: Path) -> None:
        self._state = state
        self.path = path

    # -- arranging a test ------------------------------------------------------------------------------
    @classmethod
    def init(cls, path: Path, *, branch: str = "main", config: dict[str, str] | None = None) -> Self:
        """``git init -b branch`` at ``path``."""
        state = RepoState(common=path, config={k.lower(): v for k, v in (config or {}).items()})
        state.worktrees[path] = CheckoutState(path, branch_ref(branch), main=True)
        return cls(state, path)

    @classmethod
    def clone(cls, remote: FakeRemote, path: Path) -> Self:
        """``git clone remote path``: objects, ``origin/*``, and the remote's default branch checked out."""
        branch = remote.default_branch
        state = RepoState(common=path, remotes={"origin": remote.url}, remote_repos={"origin": remote.state})
        state.config[f"branch.{branch}.remote"] = "origin"
        state.config[f"branch.{branch}.merge"] = f"refs/heads/{branch}"
        wt = CheckoutState(path, branch_ref(branch), main=True)
        state.worktrees[path] = wt
        flow.fetch(state, "origin")
        tip = state.refs.get(f"refs/remotes/origin/{branch}")
        if tip is not None:
            state.refs[branch_ref(branch)] = tip
            state.symbolic_refs["refs/remotes/origin/HEAD"] = f"refs/remotes/origin/{branch}"
            hard_to(state, wt, state.store.commits[tip].files, {})
        return cls(state, path)

    def add_remote(self, name: str, remote: FakeRemote) -> None:
        self._state.remotes[name] = remote.url
        self._state.remote_repos[name] = remote.state

    def set_remote_url(self, name: str, url: str) -> None:
        """Point ``name`` at a place that has no repository (``fetch`` and ``push`` then cannot reach it)."""
        self._state.remotes[name] = url
        self._state.remote_repos.pop(name, None)

    def set_config(self, key: str, value: str) -> None:
        self._state.config[key.lower()] = value

    def plumbing(self) -> FakePlumbing:
        """The public path-based functions over this repository's state."""
        return FakePlumbing(self._state)

    @property
    def hooks(self) -> Hooks:
        return self._state.hooks

    def drop_checkout(self, path: Path) -> None:
        """Delete a worktree's folder behind git's back (``drop_worktree`` then only forgets it)."""
        self._state.worktrees[path].missing = True

    # -- Repo ------------------------------------------------------------------------------------------
    def tag(self, name: str, rev: str) -> None:
        fake_operations.tag(self._state, self._anchor(), name, rev)

    def count(self, include: Sequence[str], exclude: Sequence[str] = ()) -> int:
        return fake_operations.count(self._state, self._anchor(), include, exclude)

    def refs(self, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
        self._anchor()
        return fake_operations.refs(self._state, prefixes)

    def ls_remote(self, remote: str, patterns: Sequence[str] = ()) -> tuple[RemoteRef, ...]:
        self._anchor()
        return fake_operations.ls_remote(self._state, remote, patterns)

    def is_ancestor(self, a: str, b: str) -> bool:
        return read.is_ancestor(self._state, self._read_anchor(), a, b)

    def merge_base(self, a: str, b: str) -> Sha | None:
        wt = self._read_anchor()
        try:
            return read.relate(self._state, wt, a, b).merge_base
        except MissingRevision:
            return None

    def cherry(self, upstream: str, head: str) -> tuple[Pick, ...]:
        wt = self._anchor()
        return read.cherry(self._state, wt, upstream, head)

    def remote_url(self, remote: str) -> str:
        self._read_anchor()
        return fake_remote.remote_url(self._state, remote)

    def fetch(self, remote: str = "origin", *, refspecs: Sequence[str] = (), timeout: float | None = None) -> None:
        _ = timeout  # In-memory operations have no elapsed process time.
        self._anchor()
        fake_remote.fetch(self._state, remote, refspecs)

    def delete_remote_at(self, remote: str, ref: str, expected: Sha) -> None:
        self._anchor()
        fake_remote.delete_remote_at(self._state, remote, ref, expected)

    def _anchor(self) -> CheckoutState:
        return FakeWorktree(self, self.path).state()

    def _read_anchor(self) -> CheckoutState:
        try:
            return self._anchor()
        except GitUnavailable as exc:
            raise GitReadFailure(str(exc)) from exc

    def identity(self) -> RepoIdentity:
        self._anchor()
        return read.identity(self._state)

    def sync(self, remote: str = "origin") -> SyncResult:
        self._anchor()
        return flow.fetch(self._state, remote)

    def relate(self, a: str, b: str) -> Relation:
        return read.relate(self._state, self._anchor(), a, b)

    def history(
        self,
        revs: Sequence[str],
        *,
        not_on: Sequence[str] = (),
        limit: int | None = None,
        patch_equivalent_to: str | None = None,
    ) -> tuple[LogEntry, ...]:
        return read.history(self._state, self._anchor(), revs, not_on=not_on, limit=limit, patch_equivalent_to=patch_equivalent_to)

    def branches(self, prefix: str = "") -> tuple[tuple[str, Sha], ...]:
        self._anchor()
        return read.branches(self._state, prefix)

    def rename_branch(self, old: str, new: str) -> None:
        checkout_ops.rename_branch(self._state, self._anchor(), old, new)

    def delete_branch(self, branch: str, *, expected: Sha) -> None:
        self._anchor()
        checkout_ops.delete_branch(self._state, branch, expected=expected)

    def tree(self, rev: str) -> Tree | None:
        return read.tree(self._state, self._anchor(), rev)

    def worktrees(self, *, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        self._anchor()
        return read.worktrees(self._state, with_dirty=with_dirty)

    def add_worktree(self, path: Path, rev: str, *, force: bool = False) -> FakeWorktree:
        wt = self._anchor()
        flow.worktree_add(self._state, path, read.resolve_commit(self._state, wt, rev), force=force)
        return FakeWorktree(self, path)

    def drop_worktree(self, path: Path, *, force: bool = False, missing_ok: bool = True) -> None:
        self._anchor()
        target = self._state.worktrees.get(path)
        if not missing_ok or (target is not None and not target.missing):
            flow.worktree_remove(self._state, path, force=force)
        if missing_ok:
            self.prune_worktrees()

    def prune_worktrees(self) -> None:
        self._anchor()
        for gone in [p for p, w in self._state.worktrees.items() if w.missing and not w.main]:
            del self._state.worktrees[gone]

    def worktree_state(self, path: Path) -> bytes | None:
        return worktree_state(self._state, path)

    def exclude_locally(self, patterns: Sequence[str]) -> None:
        self._anchor()
        self._state.info_exclude += [p for p in dict.fromkeys(patterns) if p not in self._state.info_exclude]

    def worktree(self, path: Path) -> FakeWorktree:
        return FakeWorktree(self, path)


class FakeWorktree:
    """One checkout of a :class:`FakeRepo`."""

    def __init__(self, repo: FakeRepo, path: Path) -> None:
        self.repo = repo
        self.path = path

    # -- plumbing --------------------------------------------------------------------------------------
    def _find(self) -> CheckoutState | None:
        best: CheckoutState | None = None
        for wt in self.repo._state.worktrees.values():  # noqa: SLF001 — the fake's own state
            if PurePath(wt.path) in {self.path, *self.path.parents} and (best is None or len(wt.path.parts) > len(best.path.parts)):
                best = wt
        return best

    def state(self) -> CheckoutState:
        found = self._find()
        if found is None or found.missing:
            msg = f"git exited 128: fatal: not a git repository: {self.path}"
            raise NotARepo(msg)
        return found

    @property
    def _repo(self) -> RepoState:
        return self.repo._state  # noqa: SLF001 — the fake's own state

    # -- the editor and other things that happen behind git's back --------------------------------------
    def write_file(self, rel: str, text: str | bytes) -> None:
        self.state().files[rel] = text.encode() if isinstance(text, str) else text

    def read_file(self, rel: str) -> str | None:
        data = self.state().files.get(rel)
        return None if data is None else data.decode()

    def remove_file(self, rel: str) -> None:
        self.state().files.pop(rel, None)

    def write_markers(self, rel: str) -> None:
        """A worker that left conflict markers in ``rel``."""
        self.write_file(rel, "<<<<<<< ours\nmine\n=======\ntheirs\n>>>>>>> theirs\n")

    def redirect_toplevel(self, elsewhere: Path) -> None:
        """Make git's top level for this checkout ``elsewhere`` (what a stray ``core.worktree`` does)."""
        self.state().toplevel = elsewhere

    def lock_index(self) -> None:
        """A held ``index.lock``: every write that touches the index fails with a retryable ``GitUnavailable``."""
        self.state().index_locked = True

    # -- Worktree --------------------------------------------------------------------------------------
    def health(self) -> Health:
        return read.health(self._repo, self._find(), self.path)

    def stage(self, paths: Sequence[str], *, literal: bool = True) -> None:
        fake_operations.stage(self._repo, self.state(), paths, literal=literal)

    def stage_tracked(self) -> None:
        wt = self.state()
        fake_operations.stage(self._repo, wt, list(wt.index), literal=True)

    def merge_ff(self, rev: str) -> None:
        self.repo.plumbing().merge_ff(self.path, rev)

    def branch(self) -> str | None:
        return checkout_ops.branch(self.state())

    def checkout(self, ref: str) -> None:
        checkout_ops.checkout(self._repo, self.state(), ref)

    def checkout_new(self, branch: str, start: str = "HEAD") -> None:
        checkout_ops.checkout_new(self._repo, self.state(), branch, start)

    def clean(self, keep: Sequence[str] = (), *, ignored: bool = False) -> None:
        clean(self._repo, self.state(), keep, ignored=ignored)

    def reset(self, rev: str, *, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        checkout_ops.reset(self._repo, self.state(), rev, mode=mode)

    def checkout_force(self, branch: str, start: str) -> None:
        checkout_ops.checkout_force(self._repo, self.state(), branch, start)

    def snapshot(self, base: str, *, inputs: Sequence[str] = ()) -> Snapshot:
        return read.snapshot(self._repo, self.state(), base, inputs=inputs)

    def diff(self, a: str, b: str, *, exclude: Sequence[str] = (), cap: int | None = None) -> Diff:
        return read.diff(self._repo, self.state(), a, b, exclude=tuple(exclude), cap=cap)

    def dirty(self, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        return read.dirty(self._repo, self.state(), base=base, ignored_under=tuple(ignored_under))

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
        return write.record(
            self._repo, self.state(), message, paths=paths, base=base, mode=mode, squash_to=squash_to, hooks=hooks, allow_empty=allow_empty
        )

    def take_branch(
        self,
        branch: str,
        base: str,
        *,
        mode: Literal["resume", "fresh", "restart"],
        keep_aside_as: str | None = None,
        clean_keep: Sequence[str] | None = None,
    ) -> TakeResult:
        return write.take_branch(
            self._repo, self.state(), branch=branch, base=base, mode=mode, keep_aside_as=keep_aside_as, clean_keep=clean_keep
        )

    def release_branch(self, holder: Path) -> Released | StillHeld:
        return write.release_branch(self._repo, self.state(), holder)

    def park(self, base: str, *, clean_keep: Sequence[str] | None = None) -> Sha:
        return write.park(self._repo, self.state(), base, clean_keep)

    def rebase_onto(
        self,
        base: str,
        *,
        squash_message: str | None = None,
        squash_failure: Literal["raise", "continue_unsquashed"] = "raise",
        update_refs: bool | None = None,
    ) -> RebaseResult:
        return write.rebase_onto(self._repo, self.state(), base, squash_message, squash_failure=squash_failure, update_refs=update_refs)

    def rebase(self, base: str, *, update_refs: bool | None = None) -> CommandResult:
        return fake_commands.rebase(self._repo, self.state(), base, update_refs=update_refs)

    def rebasing(self) -> bool:
        try:
            return self.state().rebase is not None
        except GitUnavailable as exc:
            raise GitReadFailure(str(exc)) from exc

    def unmerged(self) -> tuple[str, ...]:
        try:
            return tuple(sorted(self.state().unmerged, key=lambda path: path.encode("utf-8", "surrogateescape")))
        except GitUnavailable as exc:
            raise GitReadFailure(str(exc)) from exc

    def continue_rebase(self, *, stage_conflicts: bool = False, check_markers: bool = False, missing_ok: bool = False) -> CommandResult:
        return fake_commands.continue_rebase(
            self._repo, self.state(), stage_conflicts=stage_conflicts, check_markers=check_markers, missing_ok=missing_ok
        )

    def abort_rebase(self, *, missing_ok: bool = True, restore_to: Sha | None = None) -> CommandResult:
        return fake_commands.abort_rebase(self._repo, self.state(), missing_ok=missing_ok, restore_to=restore_to)

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
        _ = timeout  # In-memory operations have no elapsed process time.
        return fake_remote.push_request(
            self._repo, self.state(), remote, refspecs, options=options, force=force, allow_delete=allow_delete, hook_env=hook_env
        )

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
        _ = timeout  # In-memory operations have no elapsed process time.
        return fake_remote.push_refspecs(
            self._repo, self.state(), remote, refspecs, force=force, allow_delete=allow_delete, hook_env=hook_env
        )

    def push_lease(self, remote: str, refspec: str, *, timeout: float = 3600) -> CommandResult:
        return self.push_request(remote, [refspec], options=["--force-with-lease"], timeout=timeout)

    def lfs_push(self, remote: str, refs: Sequence[str], *, timeout: float = 3600) -> CommandResult:
        _ = remote, refs, timeout  # LFS outcomes are controlled by hooks, without transferring objects.
        self.state()
        if self._repo.hooks.lfs_spawn_failure is not None:
            raise GitUnavailable(self._repo.hooks.lfs_spawn_failure)
        if not self._repo.hooks.lfs_available:
            return CommandResult(ok=False, output="git: 'lfs' is not a git command")
        if self._repo.hooks.lfs_push_failure is not None:
            return CommandResult(ok=False, output=self._repo.hooks.lfs_push_failure)
        return CommandResult(ok=True, output="")

    def finish_rebase(self, action: Literal["continue", "abort"], *, restore_to: Sha | None = None) -> FinishResult:
        return write.finish_rebase(self._repo, self.state(), action, restore_to)

    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None) -> PushResult:
        return flow.push(self._repo, self.state(), dst, remote, hook_env or {})

    def landed(self, base: str, title_suffix: str) -> Sha | None:
        validate_revisions(base)
        wt = self.state()
        tip = self._repo.head_sha(wt)
        if tip is None or not self._repo.store.commits[tip].message.partition("\n")[0].endswith(title_suffix):
            return None
        return Sha(tip) if read.relate(self._repo, wt, tip, base).ahead == 0 else None

    def grep_tracked(self, term: str) -> tuple[str, ...]:
        return tuple(grep_files(self.state(), term))
