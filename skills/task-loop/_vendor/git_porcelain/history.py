"""Commits, history and the remote — the part of git a program that owns a repo needs.

A host that writes files and wants every change in history calls :func:`commit_paths`
with exactly the paths it touched: whatever else the user left staged or dirty is not
swept in. Identity is passed per call, so a machine with no ``user.name`` still commits,
and hooks are skipped, so a hook cannot silently stop history. :func:`log_grep` and
:func:`show_at` read that history back; :func:`push` and :func:`fetch` talk to the remote
and raise :class:`RemoteError` with a ``reason`` a host can act on (offline, auth,
rejected). :func:`merge` brings a fetched branch in with the host's identity and no hooks,
and says plainly what happened (fast-forward, merge commit, conflict, or blocked by a local
edit); :func:`finish_merge` completes a conflicted merge once a person has removed the
markers, without making them run ``git add``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from git_porcelain.errors import GitError
from git_porcelain.porcelain import _head_from_files, _run, git_returncode, has_conflict_markers, merge_in_progress, run_git, unmerged_paths

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

RemoteFailure = Literal["offline", "auth", "rejected", "other"]
MergeState = Literal["up_to_date", "fast_forward", "merged", "conflict", "blocked"]


@dataclass(frozen=True)
class Identity:
    """A commit author or committer."""

    name: str
    email: str


@dataclass(frozen=True)
class Commit:
    """A commit as :func:`log_grep` reads it."""

    sha: str
    at: datetime
    author: Identity
    subject: str
    trailers: tuple[tuple[str, str], ...] = ()
    paths: tuple[str, ...] = field(default=())


class RemoteError(GitError):
    """A push or fetch failed. ``reason`` says what a host can do about it."""

    def __init__(self, message: str, *, reason: RemoteFailure) -> None:
        super().__init__(message, retryable=reason == "offline")
        self.reason: RemoteFailure = reason


def _identity_env(author: Identity, committer: Identity) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": author.name,
        "GIT_AUTHOR_EMAIL": author.email,
        "GIT_COMMITTER_NAME": committer.name,
        "GIT_COMMITTER_EMAIL": committer.email,
    }


def _message(subject: str, trailers: Iterable[tuple[str, str]]) -> str:
    lines = [f"{key}: {value}" for key, value in trailers]
    return subject if not lines else subject + "\n\n" + "\n".join(lines) + "\n"


def _config_args(config: Mapping[str, str] | None) -> list[str]:
    """``-c key=value`` for each override, placed before the subcommand."""
    return [arg for key, value in (config or {}).items() for arg in ("-c", f"{key}={value}")]


def _known(repo: Path, specs: Sequence[str], config: list[str]) -> tuple[list[str], bool]:
    """Which of ``specs`` git can stage, and whether any of them holds an untracked file.

    One ``ls-files`` lists the tracked files under each path (deleted ones included) and the
    untracked ones that are not ignored; a path counts when it is, or holds, one of them. So
    a moved folder stages from its old path too, and an ignored, untracked path is skipped."""
    out = run_git(repo, *config, "ls-files", "-z", "-t", "--cached", "--others", "--exclude-standard", "--", *specs)
    listed = [(item[0], item[2:]) for item in out.split("\0") if len(item) > 2]
    known: list[str] = []
    untracked = False
    for spec in specs:
        path = spec.removeprefix(":(literal)")
        prefix = path.rstrip("/") + "/"
        under = [tag for tag, p in listed if p == path or p.startswith(prefix)]
        if under:
            known.append(spec)
            untracked = untracked or "?" in under
    return known, untracked


def commit_paths(
    repo: Path,
    paths: Sequence[str],
    message: str,
    *,
    author: Identity,
    committer: Identity,
    trailers: Iterable[tuple[str, str]] = (),
    config: Mapping[str, str] | None = None,
) -> str | None:
    """Commit the current content of exactly ``paths`` (additions, edits, deletions).

    Paths staged by anyone else stay staged and out of this commit. A path that neither
    exists nor is tracked is ignored. Returns the new commit's sha, or None when none of
    ``paths`` differs from ``HEAD``. Hooks that can refuse the commit are skipped
    (``--no-verify``); ``post-commit`` and auto-maintenance still run unless ``config``
    turns them off (``{"core.hooksPath": "/dev/null", "maintenance.auto": "false"}``) —
    each entry is a ``git -c key=value`` for every git call made here. Raises
    :class:`GitError` when git refuses — a held ``index.lock`` included, which is never
    removed here.

    Two git processes when nothing changed, three for a commit.
    """
    if not paths:
        return None
    cfg = _config_args(config)
    specs, untracked = _known(repo, [f":(literal){p}" for p in dict.fromkeys(paths)], cfg)
    if not specs:
        return None
    if untracked:
        # Only a new file needs staging first; `commit --only` takes tracked paths as they are.
        run_git(repo, *cfg, "add", "-A", "--", *specs)
    elif git_returncode(repo, *cfg, "diff", "--quiet", "HEAD", "--", *specs) == 0:
        return None  # the working tree matches HEAD; with no HEAD the commit below decides
    run_git(
        repo,
        *cfg,
        "commit",
        "--no-verify",
        "--only",
        "-q",
        "-m",
        _message(message, trailers),
        "--",
        *specs,
        env=_identity_env(author, committer),
    )
    return head(repo)


def head(repo: Path) -> str:
    """The sha ``HEAD`` points at (read from the ref files when they can say, else from git)."""
    return _head_from_files(repo) or run_git(repo, "rev-parse", "HEAD").strip()


_FIELD = "\x1f"
_RECORD = "\x1e"


def log_grep(repo: Path, pattern: str, *, limit: int = 20) -> list[Commit]:
    """Commits reachable from ``HEAD`` whose message matches ``pattern`` (extended regex,
    one line at a time — so ``^Key: value$`` matches a trailer), newest first, with the
    paths each one changed. Empty on a repo with no commits."""
    if not run_git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip():
        return []
    fmt = _RECORD + _FIELD.join(["%H", "%aI", "%an", "%ae", "%s", "%(trailers:only,unfold,separator=%x1d)"]) + _FIELD
    out = run_git(repo, "log", "-E", f"--grep={pattern}", f"-n{limit}", f"--format={fmt}", "--name-only", "-z", "--no-renames", "HEAD")
    commits: list[Commit] = []
    for record in out.split(_RECORD)[1:]:
        sha, at, name, email, subject, trailer_text, rest = record.split(_FIELD, 6)
        trailers = tuple(tuple(t.split(": ", 1)) for t in trailer_text.split("\x1d") if ": " in t)
        paths = tuple(p.strip("\n") for p in rest.split("\0") if p.strip("\n"))
        commits.append(
            Commit(
                sha=sha,
                at=datetime.fromisoformat(at),
                author=Identity(name, email),
                subject=subject,
                trailers=trailers,  # pyright: ignore[reportArgumentType]
                paths=paths,
            )
        )
    return commits


def show_at(repo: Path, rel: str, rev: str) -> str | None:
    """The text of ``rel`` as of ``rev``, or None when the path did not exist there."""
    try:
        return run_git(repo, "show", f"{rev}:{rel}")
    except GitError:
        return None


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """True when ``ancestor`` is reachable from ``descendant`` (a push would fast-forward)."""
    return git_returncode(repo, "merge-base", "--is-ancestor", ancestor, descendant) == 0


def upstream(repo: Path) -> str | None:
    """The current branch's upstream (``origin/main``), or None when none is set."""
    out = run_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False).strip()
    return out or None


_AUTH = re.compile(
    r"authentication failed|permission denied|could not read (username|password)|access denied|"
    r"invalid username or password|403|401|repository not found",
    re.IGNORECASE,
)
_REJECTED = re.compile(r"\[rejected\]|non-fast-forward|fetch first|failed to push some refs", re.IGNORECASE)
_OFFLINE = re.compile(
    r"could not resolve host|network is unreachable|connection (timed out|refused)|operation timed out|"
    r"unable to access|could not read from remote repository|does not appear to be a git repository|"
    r"timed out|temporary failure",
    re.IGNORECASE,
)


def classify_remote_failure(stderr: str) -> RemoteFailure:
    """Name what went wrong talking to a remote, from git's own words."""
    if _REJECTED.search(stderr):
        return "rejected"
    if _AUTH.search(stderr):
        return "auth"
    if _OFFLINE.search(stderr):
        return "offline"
    return "other"


def _remote(repo: Path, *args: str, timeout: float, config: Mapping[str, str] | None = None) -> None:
    try:
        run_git(repo, *_config_args(config), *args, timeout=timeout)
    except GitError as exc:
        reason = "offline" if exc.retryable else classify_remote_failure(str(exc))
        raise RemoteError(str(exc), reason=reason) from exc


def push(
    repo: Path,
    remote: str | None = None,
    refspec: str | None = None,
    *,
    timeout: float = 120,
    config: Mapping[str, str] | None = None,
) -> None:
    """Push the current branch to its upstream, or ``refspec`` to ``remote``. Never forces.

    ``git push`` runs the repo's ``pre-push`` hook (git-lfs installs one); ``config`` turns it
    off (``{"core.hooksPath": "/dev/null"}``) — each entry is a ``git -c key=value``."""
    args = ["push", "--porcelain"]
    if remote is not None:
        args.append(remote)
        if refspec is not None:
            args.append(refspec)
    _remote(repo, *args, timeout=timeout, config=config)


def fetch(repo: Path, remote: str | None = None, *, timeout: float = 120, config: Mapping[str, str] | None = None) -> None:
    """Fetch the remote's refs. Never touches the working tree or the current branch.

    A fetch that brings new commits starts a detached ``git maintenance run --auto``; ``config``
    turns that off (``{"maintenance.auto": "false"}``) — each entry is a ``git -c key=value``."""
    _remote(repo, "fetch", "--quiet", *([remote] if remote else []), timeout=timeout, config=config)


@dataclass(frozen=True)
class MergeResult:
    """What :func:`merge` or :func:`finish_merge` did.

    ``changed`` is every path the merge changed in the working tree (what a host re-reads);
    ``conflicted`` the paths still holding conflict markers; ``error`` git's words when a
    local edit blocked the merge.
    """

    state: MergeState
    changed: tuple[str, ...] = ()
    conflicted: tuple[str, ...] = ()
    error: str | None = None


def _changed_since(repo: Path, rev: str) -> tuple[str, ...]:
    out = run_git(repo, "-c", "core.quotePath=false", "diff", "--no-renames", "--name-only", "-z", rev, "HEAD", check=False)
    return tuple(p for p in out.split("\0") if p)


def merge(
    repo: Path,
    ref: str,
    *,
    author: Identity,
    committer: Identity,
    message: str | None = None,
    trailers: Iterable[tuple[str, str]] = (),
    config: Mapping[str, str] | None = None,
) -> MergeResult:
    """Merge ``ref`` into the current branch: fast-forward when it can, a merge commit
    (by ``author``/``committer``, hooks skipped) when both sides moved.

    A conflict leaves the merge in progress with markers in the files — the common base
    included (``diff3``), so a resolver sees what each side changed. A local edit that the
    merge would overwrite blocks it before anything changes (``blocked``). ``config`` is as
    for :func:`commit_paths`; it cannot change the conflict style.
    """
    if is_ancestor(repo, ref, "HEAD"):
        return MergeResult("up_to_date")
    before = head(repo)
    fast_forward = is_ancestor(repo, "HEAD", ref)
    # The caller's config comes first, so it cannot take the base section (diff3) away.
    args = [*_config_args(config), "-c", "merge.conflictStyle=diff3", "merge", "--no-verify", "--no-edit"]
    if message is not None:
        args += ["-m", _message(message, trailers)]
    proc = _run(repo, (*args, ref), _identity_env(author, committer), None)
    if proc.returncode != 0:
        if merge_in_progress(repo):
            return MergeResult("conflict", changed=_changed_since(repo, before), conflicted=tuple(unmerged_paths(repo)))
        return MergeResult("blocked", error=(proc.stderr or proc.stdout).strip()[:500])
    return MergeResult("fast_forward" if fast_forward else "merged", changed=_changed_since(repo, before))


def finish_merge(
    repo: Path,
    paths: Iterable[str],
    *,
    author: Identity,
    committer: Identity,
    message: str | None = None,
    trailers: Iterable[tuple[str, str]] = (),
    config: Mapping[str, str] | None = None,
) -> MergeResult:
    """Complete a conflicted merge once every conflicted file is free of markers.

    ``paths`` are the files the merge conflicted on (a host remembers them: a person who
    ran ``git add`` has cleared git's own list). Each is staged as it now stands — edited,
    or deleted to resolve it — so nobody needs to run git by hand. While any still holds
    markers, nothing is staged and the result is ``conflict``. ``config`` is as for
    :func:`commit_paths`.
    """
    if not merge_in_progress(repo):
        return MergeResult("up_to_date")
    wanted = list(dict.fromkeys([*paths, *unmerged_paths(repo)]))
    left = tuple(p for p in wanted if (repo / p).exists() and has_conflict_markers(repo / p))
    if left:
        return MergeResult("conflict", conflicted=left)
    if wanted:
        run_git(repo, "add", "-A", "--", *[f":(literal){p}" for p in wanted])
    args = [*_config_args(config), "commit", "--no-verify", "-q"]
    args += ["--no-edit"] if message is None else ["-m", _message(message, trailers)]
    run_git(repo, *args, env=_identity_env(author, committer))
    return MergeResult("merged", changed=_changed_since(repo, "HEAD^1"))


__all__ = [
    "Commit",
    "Identity",
    "MergeResult",
    "MergeState",
    "RemoteError",
    "RemoteFailure",
    "classify_remote_failure",
    "commit_paths",
    "fetch",
    "finish_merge",
    "head",
    "is_ancestor",
    "log_grep",
    "merge",
    "push",
    "show_at",
    "upstream",
]
