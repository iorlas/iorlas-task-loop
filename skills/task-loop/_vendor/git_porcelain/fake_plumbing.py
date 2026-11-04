"""The path-based plumbing surface over the fake's existing repository state."""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING

from git_porcelain import fake_flow
from git_porcelain.api import Conflict, Offline
from git_porcelain.errors import GitUnavailable, MissingRevision, NotARepo, RefRace
from git_porcelain.fake_ops import ignore_of, require_index, switch_tree, tracked_dirty
from git_porcelain.fake_store import ancestors
from git_porcelain.plumbing import Ref

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from git_porcelain.fake_store import CheckoutState, RepoState


class FakePlumbing:
    """Same path-taking functions as the public module, bound to one fake repository."""

    def __init__(self, state: RepoState) -> None:
        self.state = state

    def _checkout(self, repo: Path) -> CheckoutState:
        matches = [wt for p, wt in self.state.worktrees.items() if p == repo or p in repo.parents]
        found = max(matches, key=lambda wt: len(wt.path.parts), default=None)
        if found is None or found.missing:
            msg = f"not a git repository: {repo}"
            raise NotARepo(msg)
        return found

    def ls_remote(self, repo: Path, remote: str, *patterns: str) -> list[Ref]:
        self._checkout(repo)
        there = self.state.remote_repos.get(remote)
        if there is None:
            there = next((s for n, s in self.state.remote_repos.items() if self.state.remotes[n] == remote), None)
        if there is None or there.offline:
            msg = f"could not read from remote repository: {remote}"
            raise GitUnavailable(msg)
        refs = dict(there.refs)
        if (head := refs.get(f"refs/heads/{there.default_branch}")) is not None:
            refs["HEAD"] = head
        return [
            Ref(name, oid) for name, oid in sorted(refs.items()) if not patterns or any(_tail_match(name, pattern) for pattern in patterns)
        ]

    def branches(self, repo: Path, remote: str | None = None) -> list[Ref]:
        self._checkout(repo)
        prefix = "refs/heads/" if remote is None else f"refs/remotes/{remote}/"
        return [Ref(name[len(prefix) :], oid) for name, oid in sorted(self.state.refs.items()) if name.startswith(prefix)]

    def delete_ref_at(self, repo: Path, ref: str, oid: str) -> None:
        wt = self._checkout(repo)
        target = self.symbolic_ref(repo, ref) or ref
        current = self.state.head_sha(wt) if ref == "HEAD" else self.state.refs.get(target)
        # A zero old oid means the ref must be absent, as for update-ref.
        if current != (None if set(oid) == {"0"} else oid):
            msg = f"cannot lock ref '{ref}': incorrect old value"
            raise RefRace(msg)
        if target == "HEAD":
            wt.detached = None
        else:
            self.state.refs.pop(target, None)

    def config_get(self, repo: Path, key: str, default: str | None = None) -> str | None:
        self._checkout(repo)
        return self.state.config.get(key.lower(), default)

    def config_entries(self, repo: Path, pattern: str) -> list[tuple[str, str]]:
        self._checkout(repo)
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            msg = f"invalid config pattern: {pattern}"
            raise GitUnavailable(msg) from exc
        return [(key, value) for key, value in self.state.config.items() if matcher.search(key)]

    def symbolic_ref(self, repo: Path, name: str) -> str | None:
        wt = self._checkout(repo)
        target = wt.head_ref if name == "HEAD" else self.state.symbolic_refs.get(name)
        seen: set[str] = set()
        while target is not None and target in self.state.symbolic_refs:
            if target in seen:
                msg = f"symbolic ref loop: {name}"
                raise GitUnavailable(msg)
            seen.add(target)
            target = self.state.symbolic_refs[target]
        return target

    def merge_ff(self, repo: Path, ref: str) -> None:
        wt = self._checkout(repo)
        target = self.state.commit_named(ref, wt)
        if target is None:
            msg = f"bad revision '{ref}'"
            raise MissingRevision(msg)
        head = self.state.head_sha(wt)
        if head is not None and target in ancestors(self.state.store, head):
            return
        if head is not None and head not in ancestors(self.state.store, target):
            msg = "not possible to fast-forward"
            raise GitUnavailable(msg)
        require_index(wt)
        switch_tree(self.state, wt, self.state.store.commits[target].files, self.state.head_files(wt))
        self.state.move_head(wt, target)

    def pull_rebase(self, repo: Path, remote: str, branch: str) -> None:
        wt = self._checkout(repo)
        if tracked_dirty(wt, self.state.head_files(wt)):
            msg = "cannot pull with rebase: you have unstaged changes"
            raise GitUnavailable(msg)
        result = fake_flow.fetch(self.state, remote)
        if isinstance(result, Offline):
            raise GitUnavailable(result.tail)
        ref = f"refs/remotes/{remote}/{branch}"
        target = self.state.refs.get(ref)
        if target is None:
            msg = f"couldn't find remote ref {branch}"
            raise GitUnavailable(msg)
        head = self.state.head_sha(wt)
        if head is None or head in ancestors(self.state.store, target):
            self.merge_ff(repo, ref)
        elif target not in ancestors(self.state.store, head):
            require_index(wt)
            rebased = fake_flow.start_rebase(self.state, wt, head, target)
            if isinstance(rebased, Conflict):
                raise GitUnavailable(rebased.tail)

    def check_ignore(self, repo: Path, paths: Sequence[str]) -> set[str]:
        if not paths:
            return set()
        wt = self._checkout(repo)
        ignore = ignore_of(self.state, wt)
        prefix = repo.relative_to(wt.path).as_posix()
        return {p for p in paths if ignore.ignores(p if prefix == "." else f"{prefix}/{p}")}

    def ls_files(self, repo: Path, *, scope: str = "tracked") -> list[str]:
        wt = self._checkout(repo)
        tracked = set(wt.index)
        others = set(wt.files) - tracked
        ignore = ignore_of(self.state, wt)
        ignored = {p for p in others if ignore.ignores(p)}
        choices = {"tracked": tracked, "untracked": others - ignored, "ignored": ignored, "all": tracked | others}
        if scope not in choices:
            msg = f"unknown file scope: {scope!r}"
            raise ValueError(msg)
        prefix = repo.relative_to(wt.path).as_posix()
        if prefix == ".":
            return sorted(choices[scope])
        return sorted(p.removeprefix(prefix + "/") for p in choices[scope] if p.startswith(prefix + "/"))


def _tail_match(name: str, pattern: str) -> bool:
    return any(fnmatch.fnmatchcase(name[start:], pattern) for start in (0, *(i + 1 for i, c in enumerate(name) if c == "/")))
