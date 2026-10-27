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
from typing import TYPE_CHECKING, TypeVar

from git_porcelain import real_env, real_read, real_write
from git_porcelain.errors import GitUnavailable
from git_porcelain.real_done import Done, unavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from typing import Literal

    from git_porcelain.api import (
        Diff,
        Dirty,
        FinishResult,
        Health,
        LogEntry,
        PushResult,
        RebaseResult,
        RecordResult,
        Relation,
        Released,
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

_T = TypeVar("_T")


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
            raise GitUnavailable(msg, retryable=True) from exc
        result = Done(done.returncode, done.stdout, done.stderr.decode("utf-8", "replace"))
        if check and result.rc != 0:
            raise unavailable(args, result)
        return result

    # -- the memo --------------------------------------------------------------------------------------
    def memo(self, key: object, compute: Callable[[], _T], *, forever: bool = True) -> _T:
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

    def tree(self, rev: str) -> Tree | None:
        return real_read.tree(self, rev)

    def worktrees(self, *, with_dirty: bool = False) -> tuple[WorktreeInfo, ...]:
        return real_read.worktrees(self, with_dirty=with_dirty)

    def add_worktree(self, path: Path, rev: str) -> RealWorktree:
        return real_write.add_worktree(self, path, rev)

    def drop_worktree(self, path: Path, *, force: bool = False) -> None:
        real_write.drop_worktree(self, path, force=force)

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

    def snapshot(self, base: str) -> Snapshot:
        return real_read.snapshot(self, base)

    def diff(self, a: str, b: str, *, exclude: Sequence[str] = (), cap: int | None = None) -> Diff:
        return real_read.diff(self, a, b, exclude=tuple(exclude), cap=cap)

    def dirty(self, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        return real_read.dirty(self, base=base, ignored_under=tuple(ignored_under))

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

    def rebase_onto(self, base: str, *, squash_message: str | None = None) -> RebaseResult:
        return real_write.rebase_onto(self, base, squash_message)

    def finish_rebase(self, action: Literal["continue", "abort"], *, restore_to: Sha | None = None) -> FinishResult:
        return real_write.finish_rebase(self, action, restore_to)

    def push(self, dst: str, *, remote: str = "origin", hook_env: Mapping[str, str] | None = None) -> PushResult:
        return real_write.push(self, dst, remote, hook_env)

    def landed(self, base: str, title_suffix: str) -> Sha | None:
        return real_read.landed(self, base, title_suffix)

    def grep_tracked(self, term: str) -> tuple[str, ...]:
        return real_read.grep_tracked(self, term)
