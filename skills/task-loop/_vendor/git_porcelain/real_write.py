"""RealGit's writes. Each is one intent: it stages, commits, switches or pushes, and says what happened as a
result variant. The English-text classification of git's complaints (a lost ref lock, a network error, a hook's
refusal) is private to this file. Every write clears the mutable memo, even when it fails half-way."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from git_porcelain import real_checkout, real_observe, real_read, real_remote
from git_porcelain.api import (
    Aborted,
    BranchHeld,
    BranchTaken,
    Conflict,
    HookRejected,
    NothingToRecord,
    Offline,
    Rebased,
    Recorded,
    Released,
    Sha,
    StillHeld,
    Synced,
    UpToDate,
)
from git_porcelain.errors import some
from git_porcelain.real_done import unavailable
from git_porcelain.remote_validation import validate_remote
from git_porcelain.revision_validation import validate_revisions

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

TRANSIENT: Final = re.compile(
    r"curl \d+|Broken pipe|Connection (?:reset|timed out|refused)|Could not resolve host|early EOF|RPC failed|remote end hung up|"
    r"SSL_ERROR|TLS|Operation timed out|Network is unreachable|Temporary failure in name resolution|error: 5\d\d|HTTP/\d(?:\.\d)? 5\d\d|"
    r"Could not read from remote repository|does not appear to be a git repository|unable to access",
    re.IGNORECASE,
)
_MARKERS: Final = re.compile(r"^(?:<<<<<<<|>>>>>>>)(?: |$)", re.MULTILINE)


def _identity_args(repo: RealRepo) -> list[str]:
    who = repo.who
    return [] if who is None else ["-c", f"user.name={who.name}", "-c", f"user.email={who.email}"]


def _done[T](repo: RealRepo, result: T) -> T:
    repo.invalidate()
    return result


# -- Repo -------------------------------------------------------------------------------------------------
def sync(repo: RealRepo, remote: str) -> SyncResult:
    validate_remote(remote)
    try:
        done = real_remote.fetch_done(repo, remote, (), repo.remote_timeout)
        return Offline(done.tail, output=done.output) if done.rc else Synced(output=done.output)
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
def _stage(wt: RealWorktree, paths: Literal["own", "all", "tracked", "staged"], base: str | None) -> None:
    if paths == "staged":
        return
    if paths == "tracked":
        wt.run("add", "-u")
        return
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
    paths: Literal["own", "all", "tracked", "staged"],
    base: str | None,
    mode: Literal["new", "amend", "squash_to"],
    squash_to: Sha | None,
    hooks: bool,
    allow_empty: bool,
) -> RecordResult:
    validate_revisions(*([base] if base is not None else []), *([str(squash_to)] if squash_to is not None else []))
    if mode == "squash_to" and squash_to is None:
        msg = "mode='squash_to' needs squash_to"
        raise ValueError(msg)
    wt.run("rev-parse", "--git-dir")
    old = real_read.head_of(wt)
    try:
        if not record_prepare(wt, paths, base, mode, old, squash_to=squash_to, allow_empty=allow_empty):
            return NothingToRecord()
        if mode == "squash_to":
            wt.run("reset", "-q", "--soft", str(squash_to))
        args = record_args(message, mode, hooks=hooks, allow_empty=allow_empty)
        done = wt.repo.run(wt.path, *_identity_args(wt.repo), *args, check=False)
        if done.rc != 0:
            if mode == "squash_to" and old is not None:
                wt.run("reset", "-q", "--soft", str(old))
            return record_failure(args, done, hooks=hooks)
        head = real_read.head_of(wt)
        head = some(head)
        return Recorded(head, output=done.output)
    finally:
        wt.repo.invalidate()


def record_prepare(
    wt: RealWorktree,
    paths: Literal["own", "all", "tracked", "staged"],
    base: str | None,
    mode: Literal["new", "amend", "squash_to"],
    old: Sha | None,
    *,
    squash_to: Sha | None,
    allow_empty: bool,
) -> bool:
    """Stage the selected scope and decide whether a commit command is needed."""
    _stage(wt, paths, base)
    target = squash_to if mode == "squash_to" else old
    against = str(target) if target is not None else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    delta = wt.run("diff", "--cached", "--quiet", against, check=False)
    if delta.rc not in {0, 1}:
        raise unavailable(("diff",), delta)
    return delta.rc != 0 or allow_empty or mode == "amend"


def record_args(message: str, mode: Literal["new", "amend", "squash_to"], *, hooks: bool, allow_empty: bool) -> list[str]:
    """Build commit arguments without changing the selected index."""
    args = ["commit", "-q", *([] if hooks else ["--no-verify"]), *(["--allow-empty"] if allow_empty else [])]
    args += ["--amend", *(["-m", message] if message else ["--no-edit"])] if mode == "amend" else ["-m", message]
    return args


def record_failure(args: Sequence[str], done: Done, *, hooks: bool) -> RecordResult:
    """Keep complete command diagnostics, including hooks that never name themselves."""
    output = done.output
    if hooks and _hook_rejection(output):
        return HookRejected(output, output=output)
    raise unavailable(args, done, full_output=True)


def _hook_rejection(output: str) -> bool:
    if re.search(
        r"gpg failed|unable to sign|failed to sign|identity unknown|tell me who you are|empty ident|index\.lock|cannot lock ref|"
        r"unmerged files|unresolved conflict|nothing to amend|failed to write commit object",
        output,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\b(?:pre-commit|prepare-commit-msg|commit-msg|post-commit)\b", output, re.IGNORECASE):
        return True
    if re.search(r"\bhook\b", output, re.IGNORECASE) and re.search(r"\b(?:declined|failed|rejected)\b", output, re.IGNORECASE):
        return True
    if re.search(r"^(?:fatal:|error:|warning:|hint:|git:)", output, re.MULTILINE | re.IGNORECASE):
        return False
    # Git prefixes diagnostics and indents status details; hooks may print their own refusal verbatim.
    git_line = re.compile(
        r"^(?:fatal:|error:|warning:|hint:|git:|On branch |Changes |Unmerged |Untracked |Your branch |"
        r"You are |nothing |no changes |Aborting|\s|#)",
        re.IGNORECASE,
    )
    return any(line and not git_line.match(line) for line in output.splitlines())


def _clean(wt: RealWorktree, clean_keep: Sequence[str] | None) -> None:
    if clean_keep is not None:
        real_checkout.clean(wt, clean_keep, ignored=False)


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
    validate_revisions(branch, base)
    holders = tuple(w for w in wt.repo.worktrees() if w.branch == branch and not _same(w.path, wt.path))
    if holders:
        return BranchHeld(holders)
    base = real_checkout.resolve_commit(wt, base)
    ref = f"refs/heads/{branch}"
    exists = wt.run("rev-parse", "--verify", "-q", ref, check=False).rc == 0
    kept: str | None = None
    try:
        if mode == "resume":
            wt.run("checkout", "-q", branch, "--") if exists else wt.run("checkout", "-q", "-b", branch, "--end-of-options", base, "--")
        else:
            if mode == "fresh" and exists and keep_aside_as is not None and int(wt.run("rev-list", "--count", f"{base}..{branch}").out) > 0:
                if wt.run("rev-parse", "--verify", "-q", f"refs/heads/{keep_aside_as}", check=False).rc == 0:
                    msg = f"keep_aside_as {keep_aside_as!r} already exists"
                    raise ValueError(msg)
                wt.run("branch", "-m", "--", branch, keep_aside_as)
                kept = keep_aside_as
            wt.run("checkout", "-q", "-B", branch, "--end-of-options", base, "--")
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


def _squash_before_rebase(
    wt: RealWorktree, base: str, message: str, old: Sha, *, squash_failure: Literal["raise", "continue_unsquashed"]
) -> tuple[bool, str | None]:
    base = real_checkout.resolve_commit(wt, base)
    fork = wt.run("merge-base", "--end-of-options", "HEAD", base, check=False).out.strip()
    if not fork or _count(wt, f"{fork}..HEAD") <= 1:
        return False, None
    wt.run("reset", "-q", "--soft", fork)
    made = wt.repo.run(wt.path, *_identity_args(wt.repo), "commit", "-q", "--no-verify", "--allow-empty", "-m", message, check=False)
    if made.rc == 0:
        return True, None
    wt.run("reset", "-q", "--hard", str(old))
    if squash_failure == "raise":
        raise unavailable(("commit",), made)
    return False, made.output


def rebase_onto(
    wt: RealWorktree,
    base: str,
    squash_message: str | None,
    *,
    squash_failure: Literal["raise", "continue_unsquashed"] = "raise",
    update_refs: bool | None = None,
) -> RebaseResult:
    validate_revisions(base)
    if squash_failure not in {"raise", "continue_unsquashed"}:
        raise ValueError(squash_failure)
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
    base = real_checkout.resolve_commit(wt, base)
    if _count(wt, f"HEAD..{base}") == 0:
        return UpToDate()
    squashed = False
    squash_diagnostic: str | None = None
    try:
        if squash_message is not None:
            squashed, squash_diagnostic = _squash_before_rebase(wt, base, squash_message, old, squash_failure=squash_failure)
        flags = [] if update_refs is None else ["--update-refs" if update_refs else "--no-update-refs"]
        done = wt.run("-c", "core.editor=true", "rebase", "-q", *flags, "--end-of-options", base, check=False)
        if done.rc == 0:
            new = real_read.head_of(wt)
            new = some(new)
            return Rebased(old, new, squashed, squash_diagnostic, output=done.output)
        if _paused(wt):
            return Conflict(real_observe.unmerged(wt), done.tail, old, squash_diagnostic, output=done.output)
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
    target = real_checkout.resolve_commit(wt, str(restore_to)) if restore_to is not None else None
    paused = _paused(wt)
    try:
        if action == "abort":
            output = ""
            if paused:
                output = wt.run("rebase", "--abort").output
            if target is not None:
                output = (output + "\n" + wt.run("reset", "-q", "--hard", target).output).strip()
            head = real_read.head_of(wt)
            head = some(head)
            return Aborted(head, output=output)
        head = real_read.head_of(wt)
        head = some(head)
        if not paused:
            return Rebased(head, head, squashed=False)
        orig = _orig_head(wt)
        files = real_read.unmerged(wt)
        marked = tuple(f for f in files if has_markers(wt.path / f))
        if marked:
            return Conflict(marked, "conflict markers remain", orig)
        if files:
            wt.run("--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(files))
        done = wt.run("-c", "core.editor=true", "rebase", "--continue", check=False)
        if done.rc == 0:
            new = real_read.head_of(wt)
            new = some(new)
            return Rebased(orig, new, squashed=False, output=done.output)
        if _paused(wt):
            return Conflict(real_read.unmerged(wt), done.tail, orig, output=done.output)
        raise unavailable(("rebase",), done)
    finally:
        wt.repo.invalidate()


def has_markers(path: Path) -> bool:
    try:
        return _MARKERS.search(path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def push(wt: RealWorktree, dst: str, remote: str, hook_env: Mapping[str, str] | None, head: Sha | None = None) -> PushResult:
    """Push a pinned HEAD in two processes: rev-parse supplies the full SHA absent from porcelain.

    Pass an already known full SHA as head for a single-process typed push.
    """
    validate_remote(remote)
    if head is not None and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head) is None:
        msg = "head must be a full object id"
        raise ValueError(msg)
    head = head if head is not None else real_read.head_of(wt)
    if head is None:
        msg = "nothing to push: HEAD is unborn"
        raise ValueError(msg)
    try:
        done = wt.repo.run(
            wt.path,
            "push",
            "--porcelain",
            "--",
            remote,
            f"{head}:refs/heads/{dst}",
            check=False,
            env=hook_env,
            timeout=wt.repo.remote_timeout,
        )
    finally:
        wt.repo.invalidate()
    return real_remote.classify_push(done, head)
