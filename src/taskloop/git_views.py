"""Construct the real Git views (git_porcelain) every factory Git call runs on: the hardened environment, the discovery
ceiling, the remote-capable view and the profile port over Git objects. Wired by `composition`."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable, RealRepo, Repo

from taskloop.attempt_types import Checkouts
from taskloop.profile import NoCommit, NotAFile, Unavailable
from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo

HARDENED = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"), ("commit.gpgSign", "false"), ("maintenance.auto", "false"))
PUSH_TIMEOUT = 120.0  # seconds a publication's push or ls-remote may take (the library's default is 600)


@dataclass(frozen=True)
class GitViews:
    """The real Git views, each bounded by `read_seconds`: how long a read-only Git command may take before git_porcelain
    kills it and raises `GitTimeout` (a `GitUnavailable`, so `unavailable:git` with the command and the seconds as detail).
    The machine config's `git_read_seconds`, passed down by the composition and to each entry process in its argv."""

    read_seconds: int

    def inspect_checkout(self, path: str) -> RepoInspection:
        """Resolve the native path once and request fresh shared-library observations."""
        try:
            expanded = Path(path).expanduser()
        except RuntimeError as error:
            raise UnsupportedCheckout(f"Cannot expand checkout path: {path}") from error
        checkout = expanded.resolve()
        return inspect_repo(RealRepo(checkout, memoize=False, read_timeout=self.read_seconds), checkout)

    def checkouts(self, path: Path, *, git_dir: Path | None = None) -> Repo:
        """A fresh (unmemoized) real Git view from one checkout path, in the hardened Git environment, its discovery ceiling
        at that path: calls that run on a slot open their view from the slot itself, pinned to the verified `git_dir`
        (git_porcelain's `pins`: `<slot>/.git` is never read again, any other path is `NotARepo`)."""
        pins = None if git_dir is None else {path: git_dir}
        env = hardened(os.environ) | ceiling(path, os.environ)
        return RealRepo(path, memoize=False, env=env, read_timeout=self.read_seconds, pins=pins)

    def remotes(self, path: Path, *, git_dir: Path | None = None) -> Repo:
        """`checkouts` with a bounded transport (PUSH_TIMEOUT): the publication's view of the person's checkout. Hooks stay
        off (no `pre-push`), no push bar is added, and the person's own Git config and credentials apply; git_porcelain's
        base environment never prompts, so a locked key fails instead of hanging."""
        pins = None if git_dir is None else {path: git_dir}
        env = hardened(os.environ) | ceiling(path, os.environ)
        return RealRepo(path, memoize=False, env=env, remote_timeout=PUSH_TIMEOUT, read_timeout=self.read_seconds, pins=pins)

    def slot_profiles(self, slot: Path, gitdir: Path) -> GitProfileFiles:
        """The profile port on the slot's own view, pinned to its verified Git directory."""

        def pinned(path: Path, /, *, git_dir: Path | None = None) -> Repo:
            del git_dir
            return self.checkouts(path, git_dir=gitdir)

        return GitProfileFiles(slot, pinned)


def appended(env: Mapping[str, str], entries: Sequence[tuple[str, str]]) -> dict[str, str] | None:
    """Git env-config entries appended after any existing GIT_CONFIG_* ones (command-line scope, so no repository or
    user config file overrides them); None when the existing count is malformed."""
    count = env.get("GIT_CONFIG_COUNT") or "0"
    if not count.isascii() or not count.isdigit():
        return None
    n = int(count)
    added = {"GIT_CONFIG_COUNT": str(n + len(entries))}
    for i, (key, value) in enumerate(entries, n):
        added |= {f"GIT_CONFIG_KEY_{i}": key, f"GIT_CONFIG_VALUE_{i}": value}
    return added


def hardened(env: Mapping[str, str]) -> dict[str, str]:
    """Every factory Git call runs no hook (`--no-verify` skips only two: `prepare-commit-msg`, `post-commit`,
    `post-index-change` and `reference-transaction` would still run, from a hooks path the agent may have written), no
    fsmonitor program, no signing prompt and no automatic maintenance. This also stops `pre-push` for a later push from
    the same views; signed-commit repositories are unsupported. A malformed count is GitUnavailable (`git_config`)."""
    entries = appended(env, HARDENED)
    if entries is None:
        raise GitUnavailable("Malformed GIT_CONFIG_COUNT", hint="git_config")
    return entries


def ceiling(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """`GIT_CEILING_DIRECTORIES` with the checkout's parent first: when `<checkout>/.git` is gone, git_porcelain pins
    nothing and Git would discover an enclosing repository (a dotfiles repository at the home that holds the slots root);
    with the ceiling Git looks at the checkout itself and never above it. An ambient ceiling list is kept after it."""
    ambient = environ.get("GIT_CEILING_DIRECTORIES")
    return {"GIT_CEILING_DIRECTORIES": os.pathsep.join([str(path.parent), *([ambient] if ambient else [])])}


FILE_MODES = ("100644", "100755")  # a tree entry that is a regular file; 120000 is a symlink, 160000 a submodule


@dataclass(frozen=True)
class GitProfileFiles:
    """The profile port over Git objects: a file at a commit through git_porcelain's `Repo.tree(rev).read(path)`
    (`cat-file blob`), never the working tree. The listing decides absence, so a failed read of a listed file is
    unavailable, not missing; a symlink or submodule entry is `NotAFile`;
    a revision that names no commit (or looks like an option) is `NoCommit`, once the
    repository itself is readable (a path that is no repository is unavailable)."""

    checkout: Path
    repos: Checkouts

    def blob(self, commit: str, path: str) -> bytes | NoCommit | NotAFile | Unavailable | None:
        try:
            repo = self.repos(self.checkout)
            try:
                tree = repo.tree(f"{commit}^{{commit}}")
            except ValueError:  # git_porcelain refuses an option-like revision before running Git
                return NoCommit()
            if tree is None:
                repo.identity()  # raises when the checkout is no readable repository: a failed rev-parse proves nothing
                return NoCommit()
            if path not in tree.files:
                return None
            if (mode := tree.files[path][0]) not in FILE_MODES:  # a symlink or submodule is never the profile
                return NotAFile(mode)
            data = tree.read(path)
        except GitUnavailable as error:
            return Unavailable(str(error))
        return Unavailable(f"{path} at {commit} is listed but unreadable") if data is None else data

