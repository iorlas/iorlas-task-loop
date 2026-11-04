"""``RealRepo`` and ``RealWorktree``: the :class:`~git_porcelain.api.Repo` / ``Worktree`` protocols over the git binary.

This file holds the constructors, the one process runner (argv, env, timeout, ``GitUnavailable`` mapping) and the
memo. The reads live in ``real_read``, the writes in ``real_write``; argv, exit codes and stderr text never leave
them. Memoization is inside: immutable answers (identity, a diff between two shas, a tree) are kept for the
process; ``worktrees`` and ``branches`` are kept until an own write or :meth:`RealRepo.invalidate`; answers that
name refs are kept while the files they come from are unchanged (``real_cache``); ``health``, ``snapshot`` and
``dirty`` are never remembered, because the working tree changes behind us.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import TYPE_CHECKING

from git_porcelain import (
    real_checkout,
    real_commands,
    real_env,
    real_observe,
    real_operations,
    real_read,
    real_remote,
    real_worktrees,
    real_write,
)
from git_porcelain.errors import GitTimeout, GitUnavailable
from git_porcelain.real_done import Done, unavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from typing import Literal

    from git_porcelain.api import (
        CommandResult,
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
        Sha,
        Snapshot,
        StillHeld,
        SyncResult,
        TakeResult,
        Tree,
        WorktreeInfo,
    )
    from git_porcelain.history import Identity

__all__ = ["Done", "RealRepo", "RealWorktree", "unavailable"]


class RealRepo:
    """The git binary behind :class:`~git_porcelain.api.Repo`. ``path`` is any checkout of the repository."""

    def __init__(
        self,
        path: Path,
        *,
        identity: Identity | None = None,
        env: Mapping[str, str] | None = None,
        memoize: bool = True,
        remote_timeout: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
        observer: Callable[[tuple[str, ...]], None] | None = None,
    ) -> None:
        self.path = path
        self.who = identity
        self.extra_env = dict(env or {})
        self.memoize = memoize
        self.remote_timeout = remote_timeout
        self.sleep = sleep
        self.observer = observer
        self._forever: dict[object, object] = {}
        self._mutable: dict[object, object] = {}
        self.refs_seen: dict[object, tuple[object, object]] = {}
        self.snapshots: dict[str, tuple[object, object]] = {}

    # -- the one runner --------------------------------------------------------------------------------
    def run(
        self,
        cwd: Path,
        *args: str,
        check: bool = True,
        pin: bool = True,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Done:
        """``git -C cwd args``. A failure raises :class:`GitUnavailable` when ``check``; otherwise the caller reads ``rc``."""
        if shutil.which("git") is None:
            msg = "git not found on PATH"
            raise GitUnavailable(msg, hint="install git")
        pin_env = real_env.pinned(cwd) if pin else {}
        child = real_env.base({**self.extra_env, **pin_env, **(env or {})})
        if self.observer is not None:
            self.observer(args)
        try:
            done = subprocess.run(
                [*real_env.argv_prefix(cwd, pin_env), *args],
                check=False,
                capture_output=True,
                env=child,
                timeout=timeout,
                input=None if stdin is None else stdin.encode("utf-8", "surrogateescape"),
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"git {args[0] if args else ''} timed out after {timeout}s"
            raise GitTimeout(msg, retryable=True) from exc
        except OSError as exc:
            msg = f"failed to invoke git: {exc}"
            raise GitUnavailable(msg) from exc
        result = Done(done.returncode, done.stdout, done.stderr.decode("utf-8", "replace"))
        if check and result.rc != 0:
            raise unavailable(args, result)
        return result

    # -- the memo --------------------------------------------------------------------------------------
    def memo[T](self, key: object, compute: Callable[[], T], *, forever: bool = True) -> T:
        store = self._forever if forever else self._mutable
        if self.memoize and key in store:
            return store[key]  # type: ignore[return-value]  # keys are tagged by the call site
        value = compute()
        if self.memoize:
            store[key] = value
        return value

    def invalidate(self) -> None:
        """Forget the answers that can change: call it after something else (a worker, a hook, another process)
        changed the repository. An own write calls it itself."""
        self._mutable.clear()
        self.refs_seen.clear()

    # -- Repo ------------------------------------------------------------------------------------------
    def tag(self, name: str, rev: str) -> None:
        real_operations.tag(self, name, rev)

    def count(self, include: Sequence[str], exclude: Sequence[str] = ()) -> int:
        return real_operations.count(self, include, exclude)

    def refs(self, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
        return real_operations.refs(self, prefixes)

    def ls_remote(self, remote: str, patterns: Sequence[str] = ()) -> tuple[RemoteRef, ...]:
        return real_operations.ls_remote(self, remote, patterns)

    def is_ancestor(self, a: str, b: str) -> bool:
        return real_observe.is_ancestor(self, a, b)

    def merge_base(self, a: str, b: str) -> Sha | None:
        return real_observe.merge_base(self, a, b)

    def cherry(self, upstream: str, head: str) -> tuple[Pick, ...]:
        return real_observe.cherry(self, upstream, head)

    def remote_url(self, remote: str) -> str:
        return real_observe.remote_url(self, remote)

    def fetch(self, remote: str = "origin", *, refspecs: Sequence[str] = (), timeout: float | None = None) -> None:
        real_remote.fetch(self, remote, refspecs, timeout)

    def delete_remote_at(self, remote: str, ref: str, expected: Sha) -> None:
        real_remote.delete_remote_at(self, remote, ref, expected)

    def identity(self) -> RepoIdentity:
        return real_read.identity(self)

    def sync(self, remote: str = "origin") -> SyncResult:
        return real_write.sync(self, remote)

    def relate(self, a: str, b: str) -> Relation:
        return real_read.relate(self, a, b)

    def history(
        self,
        revs: Sequence[str],
        *,
        not_on: Sequence[str] = (),
        limit: int | None = None,
        patch_equivalent_to: str | None = None,
    ) -> tuple[LogEntry, ...]:
        return real_read.history(self, revs, not_on, limit, patch_equivalent_to)

    def branches(self, prefix: str = "") -> tuple[tuple[str, Sha], ...]:
        return real_read.branches(self, prefix)

    def rename_branch(self, old: str, new: str) -> None:
        real_checkout.rename_branch(self, old, new)

    def delete_branch(self, branch: str, *, expected: Sha) -> None:
        real_checkout.delete_branch(self, branch, expected=expected)

    def tree(self, rev: str) -> Tree | None:
        return real_read.tree(self, rev)

    def worktrees(self, *, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        return real_read.worktrees(self, with_dirty=with_dirty)

    def add_worktree(self, path: Path, rev: str, *, force: bool = False) -> RealWorktree:
        return real_worktrees.add_worktree(self, path, rev, force=force)

    def drop_worktree(self, path: Path, *, force: bool = False, missing_ok: bool = True) -> None:
        real_worktrees.drop_worktree(self, path, force=force, missing_ok=missing_ok)

    def prune_worktrees(self) -> None:
        real_worktrees.prune_worktrees(self)

    def worktree_state(self, path: Path) -> bytes | None:
        return real_worktrees.worktree_state(self, path)

    def exclude_locally(self, patterns: Sequence[str]) -> None:
        real_write.exclude_locally(self, patterns)

    def worktree(self, path: Path) -> RealWorktree:
        return RealWorktree(self, path)


class RealWorktree:
    """One checkout of a :class:`RealRepo`. Cheap to make: it reads nothing until asked."""

    def __init__(self, repo: RealRepo, path: Path) -> None:
        self.repo = repo
        self.path = path

    def run(self, *args: str, check: bool = True, pin: bool = True, stdin: str | None = None, env: Mapping[str, str] | None = None) -> Done:
        return self.repo.run(self.path, *args, check=check, pin=pin, stdin=stdin, env=env)

    def health(self) -> Health:
        return real_read.health(self)

    def stage(self, paths: Sequence[str], *, literal: bool = True) -> None:
        real_operations.stage(self, paths, literal=literal)

    def stage_tracked(self) -> None:
        real_operations.stage_tracked(self)

    def merge_ff(self, rev: str) -> None:
        real_operations.merge_ff(self, rev)

    def branch(self) -> str | None:
        return real_checkout.branch(self)

    def checkout(self, ref: str) -> None:
        real_checkout.checkout(self, ref)

    def checkout_new(self, branch: str, start: str = "HEAD") -> None:
        real_checkout.checkout_new(self, branch, start)

    def clean(self, keep: Sequence[str] = (), *, ignored: bool = False) -> None:
        real_checkout.clean(self, keep, ignored=ignored)

    def reset(self, rev: str, *, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        real_checkout.reset(self, rev, mode=mode)

    def checkout_force(self, branch: str, start: str) -> None:
        real_checkout.checkout_force(self, branch, start)

    def snapshot(self, base: str, *, inputs: Sequence[str] = ()) -> Snapshot:
        return real_read.snapshot(self, base, inputs=inputs)

    def diff(self, a: str, b: str, *, exclude: Sequence[str] = (), cap: int | None = None) -> Diff:
        return real_read.diff(self, a, b, exclude=tuple(exclude), cap=cap)

    def dirty(self, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        return real_read.dirty(self, base=base, ignored_under=tuple(ignored_under))

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
        return real_write.record(
            self, message, paths=paths, base=base, mode=mode, squash_to=squash_to, hooks=hooks, allow_empty=allow_empty
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
        return real_write.take_branch(self, branch=branch, base=base, mode=mode, keep_aside_as=keep_aside_as, clean_keep=clean_keep)

    def release_branch(self, holder: Path) -> Released | StillHeld:
        return real_write.release_branch(self, holder)

    def park(self, base: str, *, clean_keep: Sequence[str] | None = None) -> Sha:
        return real_write.park(self, base, clean_keep)

    def rebase_onto(
        self,
        base: str,
        *,
        squash_message: str | None = None,
        squash_failure: Literal["raise", "continue_unsquashed"] = "raise",
        update_refs: bool | None = None,
    ) -> RebaseResult:
        return real_write.rebase_onto(self, base, squash_message, squash_failure=squash_failure, update_refs=update_refs)

    def rebase(self, base: str, *, update_refs: bool | None = None) -> CommandResult:
        return real_commands.rebase(self, base, update_refs=update_refs)

    def rebasing(self) -> bool:
        return real_observe.rebasing(self)

    def unmerged(self) -> tuple[str, ...]:
        return real_observe.unmerged(self)

    def continue_rebase(self, *, stage_conflicts: bool = False, check_markers: bool = False, missing_ok: bool = False) -> CommandResult:
        return real_commands.continue_rebase(self, stage_conflicts=stage_conflicts, check_markers=check_markers, missing_ok=missing_ok)

    def abort_rebase(self, *, missing_ok: bool = True, restore_to: Sha | None = None) -> CommandResult:
        return real_commands.abort_rebase(self, missing_ok=missing_ok, restore_to=restore_to)

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
        return real_remote.push_request(
            self, remote, refspecs, options=options, force=force, allow_delete=allow_delete, hook_env=hook_env, timeout=timeout
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
        return real_remote.push_refspecs(self, remote, refspecs, force=force, allow_delete=allow_delete, hook_env=hook_env, timeout=timeout)

    def push_lease(self, remote: str, refspec: str, *, timeout: float = 3600) -> CommandResult:
        return self.push_request(remote, [refspec], options=["--force-with-lease"], timeout=timeout)

    def lfs_push(self, remote: str, refs: Sequence[str], *, timeout: float = 3600) -> CommandResult:
        return real_commands.command(self, ["lfs", "push", remote, *refs], timeout=timeout, lfs=True)

    def finish_rebase(self, action: Literal["continue", "abort"], *, restore_to: Sha | None = None) -> FinishResult:
        return real_write.finish_rebase(self, action, restore_to)

    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None) -> PushResult:
        return real_write.push(self, dst, remote, hook_env)

    def landed(self, base: str, title_suffix: str) -> Sha | None:
        return real_read.landed(self, base, title_suffix)

    def grep_tracked(self, term: str) -> tuple[str, ...]:
        return real_read.grep_tracked(self, term)
