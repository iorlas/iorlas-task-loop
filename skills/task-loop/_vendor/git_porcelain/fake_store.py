"""FakeGit's state: objects hashed the way git hashes them, refs, worktrees, and revision lookup.

Blobs, trees and commits are content-addressed with git's own SHA-1 framing, so ``tree_hash`` and the
blob abbreviations in a diff equal what the git binary prints for the same content. A tree is kept flat
(path to blob sha); the nested tree objects are only hashed.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from git_porcelain.errors import GitUnavailable

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["CheckoutState", "CommitObj", "Hooks", "Rebase", "RepoState", "Store", "ancestors", "blob_sha", "tree_sha"]

_CLOCK = itertools.count(1)
_STEP = re.compile(r"^(?P<base>.*?)(?P<steps>(?:~\d+|\^)*)$")
_HEX = re.compile(r"[0-9a-f]{4,40}")


def _sha(kind: str, body: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(body)}".encode() + b"\0" + body, usedforsecurity=False).hexdigest()


def blob_sha(data: bytes) -> str:
    return _sha("blob", data)


def tree_sha(files: Mapping[str, str]) -> str:
    """The id git gives the tree holding ``files`` (path to blob sha), nested folders included."""
    return _sha("tree", _tree_body(files))


def _tree_body(files: Mapping[str, str]) -> bytes:
    here: dict[str, str] = {}
    below: dict[str, dict[str, str]] = {}
    for path, sha in files.items():
        head, sep, rest = path.partition("/")
        if sep:
            below.setdefault(head, {})[rest] = sha
        else:
            here[head] = sha
    entries: list[tuple[bytes, bytes]] = []
    for name, sha in here.items():
        entries.append((name.encode(), b"100644 " + name.encode() + b"\0" + bytes.fromhex(sha)))
    for name, sub in below.items():
        entries.append((name.encode() + b"/", b"40000 " + name.encode() + b"\0" + bytes.fromhex(tree_sha(sub))))
    return b"".join(body for _, body in sorted(entries))


@dataclass(frozen=True)
class CommitObj:
    sha: str
    tree: str
    parents: tuple[str, ...]
    message: str
    files: Mapping[str, str]
    order: int


@dataclass
class Store:
    """The object database: blobs, flat trees (by tree sha) and commits."""

    blobs: dict[str, bytes] = field(default_factory=dict)
    trees: dict[str, Mapping[str, str]] = field(default_factory=dict)
    commits: dict[str, CommitObj] = field(default_factory=dict)

    def put_blob(self, data: bytes) -> str:
        sha = blob_sha(data)
        self.blobs[sha] = data
        return sha

    def put_tree(self, files: Mapping[str, str]) -> str:
        sha = tree_sha(files)
        self.trees[sha] = dict(files)
        return sha

    def put_commit(self, files: Mapping[str, str], parents: tuple[str, ...], message: str, order: int) -> CommitObj:
        tree = self.put_tree(files)
        body = f"tree {tree}\n" + "".join(f"parent {p}\n" for p in parents) + f"order {order}\n\n{message}"
        obj = CommitObj(_sha("commit", body.encode()), tree, parents, message, dict(files), order)
        self.commits[obj.sha] = obj
        return obj

    def absorb(self, other: Store) -> None:
        """Take every object of ``other`` (content-addressed, so a union is safe)."""
        self.blobs.update(other.blobs)
        self.trees.update(other.trees)
        self.commits.update(other.commits)


@dataclass
class Rebase:
    """A rebase stopped on a conflict: where to return to on abort, and what is left to replay."""

    orig_sha: str
    orig_ref: str | None
    current: str
    files: dict[str, str]
    todo: list[CommitObj] = field(default_factory=list)
    pending: CommitObj | None = None


@dataclass
class CheckoutState:
    """One checkout: HEAD (a branch ref, or a bare sha when detached), index, and files."""

    path: Path
    head_ref: str | None
    detached: str | None = None
    index: dict[str, str] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    unmerged: set[str] = field(default_factory=set)
    rebase: Rebase | None = None
    main: bool = False
    missing: bool = False
    toplevel: Path | None = None
    index_locked: bool = False


@dataclass
class Hooks:
    """What the repository's hooks do, as knobs (no hook runs in memory)."""

    refuse_commit: bool = False
    refuse_push: bool = False
    push_requires_env: dict[str, str] = field(default_factory=dict)


@dataclass
class RepoState:
    """A repository shared by its worktrees: objects, refs, config, remotes."""

    common: Path
    store: Store = field(default_factory=Store)
    refs: dict[str, str] = field(default_factory=dict)
    config: dict[str, str] = field(default_factory=dict)
    remotes: dict[str, str] = field(default_factory=dict)
    remote_repos: dict[str, RepoState] = field(default_factory=dict)
    worktrees: dict[Path, CheckoutState] = field(default_factory=dict)
    info_exclude: list[str] = field(default_factory=list)
    hooks: Hooks = field(default_factory=Hooks)
    offline: bool = False

    def tick(self) -> int:
        """A commit's place in time: one counter for every repository, so histories that meet by fetch stay ordered."""
        return next(_CLOCK)

    def head_sha(self, wt: CheckoutState) -> str | None:
        return wt.detached if wt.head_ref is None else self.refs.get(wt.head_ref)

    def head_files(self, wt: CheckoutState) -> Mapping[str, str]:
        sha = self.head_sha(wt)
        return self.store.commits[sha].files if sha else {}

    def move_head(self, wt: CheckoutState, sha: str) -> None:
        if wt.head_ref is None:
            wt.detached = sha
        else:
            self.refs[wt.head_ref] = sha

    def commit_named(self, rev: str, wt: CheckoutState) -> str | None:
        """The commit ``rev`` names: HEAD, a branch, ``origin/x``, a sha or prefix, with ``~N`` and ``^``."""
        match = _STEP.match(rev.removesuffix("^{commit}"))
        if match is None:  # pragma: no cover - the pattern matches every string
            return None
        sha = self._base(match["base"], wt)
        for step in re.findall(r"~(\d+)|\^", match["steps"]):
            for _ in range(int(step) if step else 1):
                parents = self.store.commits[sha].parents if sha else ()
                sha = parents[0] if parents else None
        return sha

    def _base(self, name: str, wt: CheckoutState) -> str | None:
        if name in {"HEAD", "@"}:
            return self.head_sha(wt)
        for prefix in ("", "refs/", "refs/heads/", "refs/remotes/"):
            if prefix + name in self.refs:
                return self.refs[prefix + name]
        if _HEX.fullmatch(name):
            found = [sha for sha in self.store.commits if sha.startswith(name)]
            return found[0] if len(found) == 1 else None
        return None

    def tree_named(self, rev: str, wt: CheckoutState) -> Mapping[str, str]:
        """The flat tree of a commit-ish or a tree sha; unknown names raise like git."""
        sha = self.commit_named(rev, wt)
        if sha:
            return self.store.commits[sha].files
        if rev in self.store.trees:
            return self.store.trees[rev]
        msg = f"git: bad revision '{rev}'"
        raise GitUnavailable(msg)

    def range_commits(self, spec: str, wt: CheckoutState) -> list[CommitObj]:
        """Commits of ``A..B`` (or everything reachable from one revision), newest first."""
        left, dots, right = spec.partition("..")
        tip = self.commit_named(right if dots else left, wt)
        if tip is None:
            msg = f"git: bad revision '{spec}'"
            raise GitUnavailable(msg)
        skip: set[str] = set()
        if dots:
            base = self.commit_named(left or "HEAD", wt)
            if base is None:
                msg = f"git: bad revision '{spec}'"
                raise GitUnavailable(msg)
            skip = ancestors(self.store, base)
        keep = ancestors(self.store, tip) - skip
        return sorted((self.store.commits[s] for s in keep), key=lambda c: -c.order)


def ancestors(store: Store, sha: str) -> set[str]:
    """``sha`` and every commit reachable from it."""
    seen: set[str] = set()
    todo = [sha]
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(store.commits[current].parents)
    return seen
