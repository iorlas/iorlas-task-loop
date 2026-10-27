"""FakeGit's reads, one function per protocol operation. Each takes the repository state (and the checkout)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from git_porcelain import ignore_rules
from git_porcelain.api import Change, Diff, Dirty, Health, LogEntry, Relation, RepoIdentity, Sha, Snapshot, Tree, TreeId, WorktreeInfo
from git_porcelain.errors import GitUnavailable
from git_porcelain.fake_diff import diff_stat, diff_text, grep_files, status_entries
from git_porcelain.fake_ignore import Ignore
from git_porcelain.fake_ops import ignore_of, is_clean
from git_porcelain.fake_store import ancestors

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from typing import Literal

    from git_porcelain.fake_store import CheckoutState, CommitObj, RepoState

__all__ = [
    "branches",
    "diff",
    "dirty",
    "grep",
    "health",
    "history",
    "identity",
    "relate",
    "resolve_commit",
    "snapshot",
    "tree",
    "worktrees",
]


def identity(repo: RepoState) -> RepoIdentity:
    common = repo.common / ".git"
    return RepoIdentity(
        repo.common, common, repo.remotes.get("origin"), hashlib.sha1(str(common).encode(), usedforsecurity=False).hexdigest()[:12]
    )


def health(repo: RepoState, wt: CheckoutState | None, path: Path) -> Health:
    config_file = repo.common / ".git" / "config"
    per_worktree = repo.config.get("extensions.worktreeconfig", "").lower() == "true"
    if "core.worktree" in repo.config:
        found = repo.config["core.worktree"]
        return Health(
            ok=False,
            problem="worktree_redirected",
            detail=f"core.worktree={found} (set in {config_file})",
            set_in=config_file,
            worktree_config=per_worktree,
        )
    if repo.config.get("core.bare", "").lower() == "true":
        detail = f"core.bare=true (set in {config_file})"
        return Health(ok=False, problem="bare", detail=detail, set_in=config_file, worktree_config=per_worktree)
    top = None if wt is None else (wt.toplevel or wt.path)
    if top != path:
        detail = f"git's top level is {top or '(none)'}, not {path}"
        return Health(ok=False, problem="toplevel_mismatch", detail=detail, set_in=None, worktree_config=per_worktree)
    return Health(ok=True, problem=None, detail="", set_in=None, worktree_config=per_worktree)


def resolve_commit(repo: RepoState, wt: CheckoutState, rev: str) -> str:
    sha = repo.commit_named(rev, wt)
    if sha is None:
        msg = f"git: bad revision '{rev}'"
        raise GitUnavailable(msg)
    return sha


def _merge_base(repo: RepoState, left: str, right: str) -> str | None:
    common = ancestors(repo.store, left) & ancestors(repo.store, right)
    return max(common, key=lambda s: repo.store.commits[s].order) if common else None


def snapshot(repo: RepoState, wt: CheckoutState, base: str) -> Snapshot:
    files = dict(repo.head_files(wt))
    ignore = ignore_of(repo, wt)
    for path, data in wt.files.items():
        if path in files or not ignore.ignores(path):
            files[path] = repo.store.put_blob(data)
    work = repo.store.put_tree({p: s for p, s in files.items() if p in wt.files})
    tip = resolve_commit(repo, wt, base)
    head = repo.head_sha(wt)
    branch = wt.head_ref.removeprefix("refs/heads/") if wt.head_ref else None
    if head is None:
        return Snapshot(TreeId(work), None, None, branch, Sha(tip), Sha(tip))
    fork = _merge_base(repo, tip, head)
    return Snapshot(TreeId(work), Sha(head), TreeId(repo.store.commits[head].tree), branch, Sha(fork or tip), Sha(tip))


def _letter(path: str, left: Mapping[str, object], right: Mapping[str, object]) -> Literal["A", "D", "M"]:
    if path not in left:
        return "A"
    return "D" if path not in right else "M"


def diff(repo: RepoState, wt: CheckoutState, a: str, b: str, *, exclude: Sequence[str], cap: int | None) -> Diff:
    left, right = repo.tree_named(a, wt), repo.tree_named(b, wt)
    stats = diff_stat(left, right, repo.store, exclude)
    if not stats:
        return Diff((), "", truncated=False)
    changes = tuple(Change(s.path, _letter(s.path, left, right), s.added, s.deleted) for s in stats)
    if cap == 0:
        return Diff(changes, "", truncated=True)
    patch = diff_text(left, right, repo.store, exclude)
    return Diff(changes, patch[:cap], truncated=True) if cap is not None and len(patch) > cap else Diff(changes, patch, truncated=False)


def dirty(repo: RepoState, wt: CheckoutState, *, base: str | None, ignored_under: Sequence[str]) -> Dirty:
    entries = status_entries(repo.head_files(wt), wt, ignore_of(repo, wt))
    tracked = sorted({p for e in entries if e.code != "??" for p in (e.path, e.orig_path) if p})
    untracked = tuple(sorted(e.path for e in entries if e.code == "??"))
    ignored_by_base: frozenset[str] = frozenset()
    if base is not None and untracked:
        rules = Ignore(ignore_rules.flatten(_ignore_files(repo, resolve_commit(repo, wt, base))))
        ignored_by_base = frozenset(p for p in untracked if rules.ignores(p))
    ignored: tuple[str, ...] = ()
    if ignored_under:
        mine = ignore_of(repo, wt)
        prefixes = tuple(p.rstrip("/") for p in ignored_under)
        ignored = tuple(
            sorted(p for p in wt.files if p not in wt.index and mine.ignores(p) and any(p == q or p.startswith(q + "/") for q in prefixes))
        )
    return Dirty(tuple(tracked), untracked, ignored_by_base, ignored)


def _ignore_files(repo: RepoState, commit: str) -> dict[str, str]:
    files = repo.store.commits[commit].files
    return {p: repo.store.blobs[s].decode("utf-8", "replace") for p, s in files.items() if ignore_rules.is_ignore_file(p)}


def relate(repo: RepoState, wt: CheckoutState, a: str, b: str) -> Relation:
    left, right = resolve_commit(repo, wt, a), resolve_commit(repo, wt, b)
    mine, theirs = ancestors(repo.store, left), ancestors(repo.store, right)
    fork = _merge_base(repo, left, right)
    return Relation(Sha(fork) if fork else None, len(mine - theirs), len(theirs - mine))


def _patch_id(repo: RepoState, commit: CommitObj) -> frozenset[tuple[str, tuple[str, ...]]]:
    before = repo.store.commits[commit.parents[0]].files if commit.parents else {}
    found: list[tuple[str, tuple[str, ...]]] = []
    for path in sorted(set(before) | set(commit.files)):
        if before.get(path) != commit.files.get(path):
            text = diff_text(
                {path: before[path]} if path in before else {}, {path: commit.files[path]} if path in commit.files else {}, repo.store
            )
            found.append((path, tuple(ln for ln in text.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))))
    return frozenset(found)


def history(
    repo: RepoState, wt: CheckoutState, revs: Sequence[str], *, not_on: Sequence[str], limit: int | None, patch_equivalent_to: str | None
) -> tuple[LogEntry, ...]:
    if patch_equivalent_to is not None and len(revs) != 1:
        msg = "patch_equivalent_to needs exactly one rev"
        raise ValueError(msg)
    keep: set[str] = set()
    for rev in revs:
        keep |= ancestors(repo.store, resolve_commit(repo, wt, rev))
    for rev in not_on:
        keep -= ancestors(repo.store, resolve_commit(repo, wt, rev))
    commits = sorted((repo.store.commits[s] for s in keep), key=lambda c: -c.order)[:limit]
    on_base: set[str] = set()
    ids: set[frozenset[tuple[str, tuple[str, ...]]]] = set()
    if patch_equivalent_to is not None:
        up = ancestors(repo.store, resolve_commit(repo, wt, patch_equivalent_to))
        on_base = up
        ids = {_patch_id(repo, repo.store.commits[s]) for s in up - ancestors(repo.store, resolve_commit(repo, wt, revs[0]))}
    return tuple(
        LogEntry(
            Sha(c.sha),
            c.order,
            c.message.partition("\n")[0],
            c.message.partition("\n")[2].strip("\n"),
            None if patch_equivalent_to is None else c.sha in on_base or _patch_id(repo, c) in ids,
        )
        for c in commits
    )


def branches(repo: RepoState, prefix: str) -> tuple[tuple[str, Sha], ...]:
    heads = ((r.removeprefix("refs/heads/"), Sha(s)) for r, s in repo.refs.items() if r.startswith("refs/heads/"))
    return tuple(sorted(row for row in heads if row[0].startswith(prefix)))


def tree(repo: RepoState, wt: CheckoutState, rev: str) -> Tree | None:
    sha = repo.commit_named(rev, wt)
    files: Mapping[str, str] | None = repo.store.commits[sha].files if sha else repo.store.trees.get(rev)
    if files is None:
        return None
    named = Sha(sha or rev)
    return Tree(
        named,
        lambda: {p: ("100644", Sha(b)) for p, b in files.items()},
        lambda path: repo.store.blobs[files[path]] if path in files else None,
    )


def worktrees(repo: RepoState, *, with_dirty: bool) -> tuple[WorktreeInfo, ...]:
    every = repo.worktrees.values()
    ordered = [w for w in every if w.main] + sorted((w for w in every if not w.main), key=lambda w: w.path.name)
    return tuple(
        WorktreeInfo(
            w.path,
            Sha(head) if (head := repo.head_sha(w)) else None,
            w.head_ref.removeprefix("refs/heads/") if w.head_ref else None,
            w.main,
            (not is_clean(repo, w) if not w.missing else None) if with_dirty else None,
        )
        for w in ordered
    )


def grep(wt: CheckoutState, term: str) -> tuple[str, ...]:
    return tuple(grep_files(wt, term))
