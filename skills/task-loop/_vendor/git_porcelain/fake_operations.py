"""Small task-loop operations over the fake's shared objects and checkout index."""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

from git_porcelain import fake_ops
from git_porcelain.api import RefEntry, RemoteRef, RemoteRefs, Sha
from git_porcelain.errors import GitUnavailable, TagExists
from git_porcelain.fake_read import resolve_commit
from git_porcelain.fake_store import ancestors
from git_porcelain.remote_validation import validate_remote
from git_porcelain.revision_validation import validate_revisions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from git_porcelain.fake_store import CheckoutState, RepoState


def tag(repo: RepoState, wt: CheckoutState, name: str, rev: str) -> None:
    validate_revisions(rev)
    target = rev if rev in repo.store.trees or rev in repo.store.blobs else resolve_commit(repo, wt, rev)
    ref = f"refs/tags/{name}"
    if ref in repo.refs:
        msg = f"fatal: tag '{name}' already exists"
        raise TagExists(msg)
    repo.refs[ref] = target


def count(repo: RepoState, wt: CheckoutState, include: Sequence[str], exclude: Sequence[str]) -> int:
    if not include:
        return 0
    validate_revisions(*include, *exclude)
    keep: set[str] = set()
    skip: set[str] = set()
    for rev in include:
        positive, negative = revision_sets(repo, wt, rev)
        keep.update(positive)
        skip.update(negative)
    for rev in exclude:
        negative, positive = revision_sets(repo, wt, rev)
        keep.update(positive)
        skip.update(negative)
    return len(keep - skip)


def revision_sets(repo: RepoState, wt: CheckoutState, rev: str) -> tuple[set[str], set[str]]:
    """Reachability selection for revision names, negations and two/three-dot ranges."""
    if rev.startswith("^"):
        positive, negative = revision_sets(repo, wt, rev[1:])
        return negative, positive
    if "..." in rev:
        left, _, right = rev.partition("...")
        a = ancestors(repo.store, resolve_commit(repo, wt, left or "HEAD"))
        b = ancestors(repo.store, resolve_commit(repo, wt, right or "HEAD"))
        return a | b, a & b
    if ".." in rev:
        left, _, right = rev.partition("..")
        return (
            ancestors(repo.store, resolve_commit(repo, wt, right or "HEAD")),
            ancestors(repo.store, resolve_commit(repo, wt, left or "HEAD")),
        )
    return ancestors(repo.store, resolve_commit(repo, wt, rev)), set()


def refs(repo: RepoState, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
    """List sorted full ref names; empty prefixes intentionally select every ref."""
    names = {**repo.refs, **{name: repo.refs[target] for name, target in repo.symbolic_refs.items() if target in repo.refs}}
    return tuple(
        RefEntry(name, Sha(oid))
        for name, oid in sorted(names.items())
        if name.startswith("refs/") and (not prefixes or any(ref_matches(name, prefix) for prefix in prefixes))
    )


def ref_matches(name: str, prefix: str) -> bool:
    """Match a for-each-ref prefix or glob at a ref component boundary."""
    return name == prefix or name.startswith(prefix.rstrip("/") + "/") or fnmatch.fnmatchcase(name, prefix)


def ls_remote(repo: RepoState, remote: str, patterns: Sequence[str]) -> RemoteRefs:
    validate_remote(remote)
    name = next((key for key, url in repo.remotes.items() if url == remote), remote)
    there = repo.remote_repos.get(name)
    if there is None or there.offline:
        msg = f"could not read from remote repository: {remote}"
        raise GitUnavailable(msg)
    rows = dict(there.refs)
    if (head := rows.get(f"refs/heads/{there.default_branch}")) is not None:
        rows["HEAD"] = head
    refs = [RemoteRef(ref, Sha(oid)) for ref, oid in sorted(rows.items()) if not patterns or any(tail_match(ref, p) for p in patterns)]
    return RemoteRefs(refs, output="\n".join(f"{row.oid}\t{row.name}" for row in refs))


def tail_match(name: str, pattern: str) -> bool:
    """Git's ls-remote globs match at the start or immediately after a slash."""
    return any(fnmatch.fnmatchcase(name[start:], pattern) for start in (0, *(i + 1 for i, c in enumerate(name) if c == "/")))


def stage(repo: RepoState, wt: CheckoutState, paths: Sequence[str], *, literal: bool) -> None:
    if not paths:
        return
    picks: list[str] = []
    names = set(wt.files) | set(wt.index)
    for spec in paths:
        if literal:
            picks.append(spec)
        else:
            matches = sorted(p for p in names if fnmatch.fnmatchcase(p, spec) or p.startswith(spec.rstrip("/") + "/"))
            picks.extend(matches or [spec])
    fake_ops.stage(repo, wt, picks)
