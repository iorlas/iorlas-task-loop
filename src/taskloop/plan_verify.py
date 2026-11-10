"""Read-only Git evidence for a returned plan answer: the slot's state, and the verdict over (B, X, the chain, the plan blob).

Git only, through `git_porcelain`: no Git write, process, lock, ref, push or factory.db access. Identity is read through
the slot; every commit read and the worktree listing run from the person's checkout (`RepoIdentity.root`); only the
status read runs on the slot. `GitUnavailable` and `Unreadable` propagate: they mean unknown, never a verdict.
"""

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal

from git_porcelain import Repo, Tree

from taskloop.plan_types import Checkouts, Rejected, Rule, Verdict, Verified

type Problem = Literal["unborn", "branch", "head_moved", "dirty"]
CHAIN_CAP: Final = 8  # a plan step commits the plan and perhaps a few design artifacts
PLAN_CAP: Final = 1 << 20  # bytes, known only after the full read: a tree listing carries no sizes
MODE: Final = "100644"
FORBIDDEN: Final = frozenset({"", ".", "..", ".git"})  # compared case-folded: macOS file systems ignore case


class Unreadable(Exception):
    """A read that cannot be told apart from a failure returned nothing: a parent of a chain commit, a listed blob, or a
    listed path's entry. The library reads these with an unchecked exit code, so None is never taken as evidence."""


@dataclass(frozen=True)
class SlotState:
    root: Path
    head: str | None
    branch: str | None
    dirty: bool

    def problem(self, at: str | None = None) -> Problem | None:
        """None when the slot is born, detached, clean and (given `at`) at that commit."""
        if self.head is None:
            return "unborn"
        if self.branch is not None:
            return "branch"
        if at is not None and self.head != at:
            return "head_moved"
        return "dirty" if self.dirty else None


def observe_slot(checkouts: Checkouts, cwd: str, repo_id: str) -> SlotState | Literal["repo", "not_listed"]:
    """`repo` when the slot's repository is not `repo_id`; `not_listed` when Git does not list the slot."""
    path = Path(cwd)
    slot = checkouts(path)
    identity = slot.identity()
    if identity.key != repo_id:
        return "repo"
    info = next((worktree for worktree in checkouts(identity.root).worktrees() if worktree.path == path), None)
    if info is None:
        return "not_listed"
    return SlotState(identity.root, info.head, info.branch, slot.worktree(path).dirty().raw)


def allowed(path: str, task_id: str) -> bool:
    """Under `docs/design/<task-id>/`, with no empty, `.`, `..` or `.git` component in any case."""
    parts = path.split("/")
    return parts[:3] == ["docs", "design", task_id] and len(parts) > 3 and not any(part.casefold() in FORBIDDEN for part in parts)


def judge(repo: Repo, root: Path, base: str, commit: str, task_id: str, plan_path: str) -> Verdict:
    """The section 3 rules in order; the first broken one decides. Every read is of content-addressed objects."""
    tip = repo.tree(f"{commit}^{{commit}}")
    if tip is None or tip.sha != commit:  # never a tag, tree or abbreviation that resolves to some other commit
        return Rejected("commit_absent")
    relation = repo.relate(base, commit)
    if relation.ahead != 0:
        return Rejected("not_descendant")
    if relation.behind > CHAIN_CAP:
        return Rejected("chain_length")
    broken = _chain(repo, root, tip, base, relation.behind, task_id)
    return Rejected(broken) if broken is not None else _plan(tip, plan_path, task_id, reused=relation.behind == 0)


def _chain(repo: Repo, root: Path, tip: Tree, base: str, steps: int, task_id: str) -> Rule | None:
    """Exactly `steps` first-parent steps from X reach B, and not before (else a merge brought in outside commits);
    then every commit of the chain changes only allowed files, added or modified, with mode 100644. A missing parent is
    unknown, not a merge: a root commit and a failed read look the same."""
    trees = [tip]
    for _ in range(steps):
        if trees[-1].sha == base:
            return "merge"
        parent = repo.tree(f"{trees[-1].sha}^")
        if parent is None:
            raise Unreadable("parent")
        trees.append(parent)
    if trees[-1].sha != base:
        return "merge"
    checkout = repo.worktree(root)
    for child, parent in pairwise(trees):
        for change in checkout.diff(parent.sha, child.sha, cap=0).changes:
            if change.kind == "D" or not allowed(change.path, task_id):
                return "paths"
            entry = child.files.get(change.path)
            if entry is None:
                raise Unreadable("entry")
            if entry[0] != MODE:
                return "mode"
    return None


def _plan(tip: Tree, plan_path: str, task_id: str, *, reused: bool) -> Verdict:
    """The plan at X passes the path and mode rules and the content floor; never a review of what it says."""
    entry = tip.files.get(plan_path)
    if not allowed(plan_path, task_id):
        return Rejected("paths")
    if entry is None:
        return Rejected("plan_missing")
    if entry[0] != MODE:
        return Rejected("mode")
    data = tip.read(plan_path)
    if data is None:  # the listing has the plan: an empty read is a failed read
        raise Unreadable("blob")
    broken = _content(data)
    return Verified(entry[1], reused) if broken is None else Rejected(broken)


def _content(data: bytes) -> Rule | None:
    """Strict UTF-8, not whitespace only, at most PLAN_CAP bytes after the full read."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "plan_encoding"
    if not text.strip():
        return "plan_empty"
    return "plan_size" if len(data) > PLAN_CAP else None
