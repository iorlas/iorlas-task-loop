"""RealGit's writes. Each is one intent: it stages, commits, switches or pushes, and says what happened as a
result variant. The English-text classification of git's complaints (a lost ref lock, a network error, a hook's
refusal) is private to this file. Every write clears the mutable memo, even when it fails half-way."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal, TypeVar

from git_porcelain import real_parse, real_read
from git_porcelain.api import (
    Aborted,
    BranchHeld,
    BranchTaken,
    Conflict,
    HookRejected,
    NothingToRecord,
    Offline,
    Pushed,
    Rebased,
    Recorded,
    Rejected,
    Released,
    Sha,
    StillHeld,
    Synced,
    Transient,
    UpToDate,
)
from git_porcelain.errors import GitUnavailable, some
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from git_porcelain.api import (
        FinishResult,
        PushResult,
        RebaseResult,
        RecordResult,
        SyncResult,
        TakeResult,
    )
    from git_porcelain.real import RealRepo, RealWorktree
    from git_porcelain.real_done import Done

__all__ = [
    "add_worktree",
    "drop_worktree",
    "exclude_locally",
    "finish_rebase",
    "park",
    "push",
    "rebase_onto",
    "record",
    "release_branch",
    "sync",
    "take_branch",
]

# Another process fetching into the same repository at the same moment: the ref is where it should be, the fetch
# only lost the lock (task-loop measured 150 of 180 simultaneous fetches failing so).
_REF_RACE: Final = re.compile(
    r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'|failed: reference already exists"
)
_FETCH_TRIES: Final = 5
_TRANSIENT: Final = re.compile(
    r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|remote end hung up|"
    r"SSL_ERROR|TLS|Operation timed out|Network is unreachable|Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d|"
    r"Could not read from remote repository|does not appear to be a git repository|unable to access",
    re.IGNORECASE,
)
_NOT_A_HOOK: Final = ("index.lock", "tell me who you are", "empty ident", "unable to auto-detect", "not a git repository", "unmerged files")
_MARKERS: Final = re.compile(r"^(?:<<<<<<<|>>>>>>>)(?: |$)", re.MULTILINE)


def _identity_args(repo: RealRepo) -> list[str]:
    who = repo.who
    return [] if who is None else ["-c", f"user.name={who.name}", "-c", f"user.email={who.email}"]


T = TypeVar("T")


def _done(repo: RealRepo, result: T) -> T:
    repo.invalidate()
    return result


# -- Repo -------------------------------------------------------------------------------------------------
def sync(repo: RealRepo, remote: str) -> SyncResult:
    try:
        for attempt in range(_FETCH_TRIES):
            done = repo.run(repo.path, "fetch", "--quiet", remote, check=False, timeout=repo.remote_timeout)
            if done.rc == 0:
                return Synced()
            if attempt == _FETCH_TRIES - 1 or not _REF_RACE.search(done.tail):
                return Offline(done.tail)
            repo.sleep(0.1 * (attempt + 1))
        return Offline("fetch gave up")  # pragma: no cover - the loop returns on its last turn
    finally:
        repo.invalidate()


def add_worktree(repo: RealRepo, path: Path, rev: str) -> RealWorktree:
    try:
        repo.run(repo.path, "worktree", "add", "-q", "--detach", str(path), rev)
    finally:
        repo.invalidate()
    return repo.worktree(path)


def drop_worktree(repo: RealRepo, path: Path, *, force: bool) -> None:
    try:
        if path.exists():
            repo.run(repo.path, "worktree", "remove", *(["--force"] if force else []), str(path))
        repo.run(repo.path, "worktree", "prune")
    finally:
        repo.invalidate()


def exclude_locally(repo: RealRepo, patterns: Sequence[str]) -> None:
    target = repo.identity().common_dir / "info" / "exclude"
    have = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    missing = [p for p in dict.fromkeys(patterns) if p not in have]
    if not missing:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    keep = "\n" if have and not target.read_text(encoding="utf-8").endswith("\n") else ""
    with target.open("a", encoding="utf-8") as handle:
        handle.write(keep + "\n".join(missing) + "\n")


# -- Worktree ---------------------------------------------------------------------------------------------
def _stage(wt: RealWorktree, paths: Literal["own", "all"], base: str | None) -> None:
    if paths == "all":
        wt.run("add", "-A")
        return
    state = real_read.dirty(wt, base, ())
    picks = [*state.tracked, *(p for p in state.untracked if p not in state.base_ignored)]
    if picks:
        wt.run("--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(picks))


def record(
    wt: RealWorktree,
    message: str,
    *,
    paths: Literal["own", "all"],
    base: str | None,
    mode: Literal["new", "amend", "squash_to"],
    squash_to: Sha | None,
    hooks: bool,
    allow_empty: bool,
) -> RecordResult:
    if mode == "squash_to" and squash_to is None:
        msg = "mode='squash_to' needs squash_to"
        raise ValueError(msg)
    old = real_read.head_of(wt)
    if mode == "amend" and old is None:
        msg = "nothing to amend: HEAD is unborn"
        raise ValueError(msg)
    try:
        _stage(wt, paths, base)
        target = squash_to if mode == "squash_to" else old
        against = str(target) if target is not None else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # the empty tree
        if wt.run("diff", "--cached", "--quiet", against, check=False).rc == 0 and not allow_empty:
            return NothingToRecord()
        if mode == "squash_to":
            wt.run("reset", "-q", "--soft", str(squash_to))
        args = ["commit", "-q", *([] if hooks else ["--no-verify"]), *(["--allow-empty"] if allow_empty else [])]
        args += ["--amend", *(["-m", message] if message else ["--no-edit"])] if mode == "amend" else ["-m", message]
        done = wt.repo.run(wt.path, *_identity_args(wt.repo), *args, check=False)
        if done.rc != 0:
            if mode == "squash_to" and old is not None:
                wt.run("reset", "-q", "--soft", str(old))
            if hooks and not any(mark in done.tail.lower() for mark in _NOT_A_HOOK):
                return HookRejected(done.tail)
            raise unavailable(args, done)
        head = real_read.head_of(wt)
        head = some(head)
        return Recorded(head)
    finally:
        wt.repo.invalidate()


def _clean(wt: RealWorktree, clean_keep: Sequence[str] | None) -> None:
    if clean_keep is not None:
        wt.run("clean", "-fdq", *(arg for pattern in clean_keep for arg in ("-e", pattern)))


def _same(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()


def take_branch(
    wt: RealWorktree,
    *,
    branch: str,
    base: str,
    mode: Literal["resume", "fresh", "restart"],
    keep_aside_as: str | None,
    clean_keep: Sequence[str] | None,
) -> TakeResult:
    holders = tuple(w for w in wt.repo.worktrees() if w.branch == branch and not _same(w.path, wt.path))
    if holders:
        return BranchHeld(holders)
    ref = f"refs/heads/{branch}"
    exists = wt.run("rev-parse", "--verify", "-q", ref, check=False).rc == 0
    kept: str | None = None
    try:
        if mode == "resume":
            wt.run("checkout", "-q", branch, "--") if exists else wt.run("checkout", "-q", "-b", branch, base)
        else:
            if mode == "fresh" and exists and keep_aside_as is not None and int(wt.run("rev-list", "--count", f"{base}..{branch}").out) > 0:
                if wt.run("rev-parse", "--verify", "-q", f"refs/heads/{keep_aside_as}", check=False).rc == 0:
                    msg = f"keep_aside_as {keep_aside_as!r} already exists"
                    raise ValueError(msg)
                wt.run("branch", "-m", branch, keep_aside_as)
                kept = keep_aside_as
            wt.run("checkout", "-q", "-B", branch, base)
        _clean(wt, clean_keep)
        head = real_read.head_of(wt)
        head = some(head)
        return BranchTaken(branch, head, created=not exists or kept is not None, kept_aside=kept)
    finally:
        wt.repo.invalidate()


def release_branch(wt: RealWorktree, holder: Path) -> Released | StillHeld:
    info = next((w for w in wt.repo.worktrees() if _same(w.path, holder)), None)
    if info is None or _same(holder, wt.path):
        msg = f"{holder} is not another worktree of this repository"
        raise ValueError(msg)
    if info.is_main:
        return StillHeld(holder, "the main checkout holds it")
    other = wt.repo.worktree(holder)
    try:
        if not real_read.dirty(other, None, ()).raw and wt.run("worktree", "remove", str(holder), check=False).rc == 0:
            return Released(holder, "removed")
        done = other.run("checkout", "-q", "--detach", check=False)
        return Released(holder, "detached") if done.rc == 0 else StillHeld(holder, done.tail)
    finally:
        wt.repo.invalidate()


def park(wt: RealWorktree, base: str, clean_keep: Sequence[str] | None) -> Sha:
    try:
        wt.run("checkout", "-q", "--detach", base)
        _clean(wt, clean_keep)
    finally:
        wt.repo.invalidate()
    return some(real_read.head_of(wt))


def _paused(wt: RealWorktree) -> bool:
    gd = real_read.git_dir_of(wt)
    return (gd / "rebase-merge").is_dir() or (gd / "rebase-apply").is_dir()


def _count(wt: RealWorktree, spec: str) -> int:
    return int(wt.run("rev-list", "--count", spec).out.strip())


def rebase_onto(wt: RealWorktree, base: str, squash_message: str | None) -> RebaseResult:
    if _paused(wt):
        msg = "a rebase is already paused here: finish_rebase first"
        raise ValueError(msg)
    if real_read.dirty(wt, None, ()).tracked:
        msg = "dirty: the tree has tracked changes"
        raise ValueError(msg)
    old = real_read.head_of(wt)
    if old is None:
        msg = "nothing to rebase: HEAD is unborn"
        raise ValueError(msg)
    if _count(wt, f"HEAD..{base}") == 0:
        return UpToDate()
    squashed = False
    try:
        if squash_message is not None:
            fork = wt.run("merge-base", "HEAD", base, check=False).out.strip()
            if fork and _count(wt, f"{fork}..HEAD") > 1:
                wt.run("reset", "-q", "--soft", fork)
                made = wt.repo.run(
                    wt.path, *_identity_args(wt.repo), "commit", "-q", "--no-verify", "--allow-empty", "-m", squash_message, check=False
                )
                if made.rc != 0:
                    wt.run("reset", "-q", "--hard", str(old))
                    raise unavailable(("commit",), made)
                squashed = True
        done = wt.run("-c", "rebase.updateRefs=false", "-c", "core.editor=true", "rebase", "-q", base, check=False)
        if done.rc == 0:
            new = real_read.head_of(wt)
            new = some(new)
            return Rebased(old, new, squashed)
        if _paused(wt):
            return Conflict(real_read.unmerged(wt), done.tail, old)
        if squashed:
            wt.run("reset", "-q", "--hard", str(old))
        raise unavailable(("rebase",), done)
    finally:
        wt.repo.invalidate()


def _orig_head(wt: RealWorktree) -> Sha:
    gd = real_read.git_dir_of(wt)
    for name in ("rebase-merge", "rebase-apply"):
        try:
            return Sha((gd / name / "orig-head").read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return real_read.head_of(wt) or Sha("")


def finish_rebase(wt: RealWorktree, action: Literal["continue", "abort"], restore_to: Sha | None) -> FinishResult:
    paused = _paused(wt)
    try:
        if action == "abort":
            if paused:
                wt.run("rebase", "--abort")
            if restore_to is not None:
                wt.run("reset", "-q", "--hard", str(restore_to))
            head = real_read.head_of(wt)
            head = some(head)
            return Aborted(head)
        head = real_read.head_of(wt)
        head = some(head)
        if not paused:
            return Rebased(head, head, squashed=False)
        orig = _orig_head(wt)
        files = real_read.unmerged(wt)
        marked = tuple(f for f in files if _has_markers(wt.path / f))
        if marked:
            return Conflict(marked, "conflict markers remain", orig)
        if files:
            wt.run("--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(files))
        done = wt.run("-c", "core.editor=true", "rebase", "--continue", check=False)
        if done.rc == 0:
            new = real_read.head_of(wt)
            new = some(new)
            return Rebased(orig, new, squashed=False)
        if _paused(wt):
            return Conflict(real_read.unmerged(wt), done.tail, orig)
        raise unavailable(("rebase",), done)
    finally:
        wt.repo.invalidate()


def _has_markers(path: Path) -> bool:
    try:
        return _MARKERS.search(path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def push(wt: RealWorktree, dst: str, remote: str, hook_env: Mapping[str, str] | None) -> PushResult:
    head = real_read.head_of(wt)
    if head is None:
        msg = "nothing to push: HEAD is unborn"
        raise ValueError(msg)
    try:
        done = wt.repo.run(
            wt.path, "push", "--porcelain", remote, f"HEAD:refs/heads/{dst}", check=False, env=hook_env, timeout=wt.repo.remote_timeout
        )
    finally:
        wt.repo.invalidate()
    return _classify_push(done, head)


def _classify_push(done: Done, head: Sha) -> PushResult:
    if done.rc == 0:
        return Pushed(head)
    if any(line.flag == "!" for line in real_parse.parse_push(done.out)):
        return Rejected(done.tail)
    if _TRANSIENT.search(done.tail):
        return Transient(done.tail)
    if "failed to push some refs" in done.err or done.out.strip() == "" or "pre-push" in done.err:
        return HookRejected(done.tail)
    msg = f"git push exited {done.rc}: {done.tail}"
    raise GitUnavailable(msg)
