"""The verdict over a step's chain: attempt 1's B, each attempt's commit, the step kind's own rule at the last (its
artifact, the plan blob).

Git only, through `git_porcelain`: no Git write, process, lock, ref, push or factory.db access. Every commit read runs
from the person's checkout (the root the verified slot pointer names). `GitUnavailable` and `Unreadable` propagate: they
mean unknown, never a verdict.
"""

from pathlib import Path

from git_porcelain import Repo, Tree

from taskloop.attempt_types import MODE, ChainLink, Rejected, Rule, StepRules, Unreadable, Verdict, Verified, path_allowed
from taskloop.steps import StepKind


def judge(repo: Repo, root: Path, commit: str, step: StepKind, rules: StepRules, steps: tuple[ChainLink, ...]) -> Verdict:
    """The rules in order over the step's chain; the first broken one decides. Every read is of content-addressed
    objects. S: each earlier attempt of effect `commit`'s stored X, then `commit` (Xn) when the last attempt's effect is
    `commit`. Xn is len(S) first-parent commits on attempt 1's B, each S_k one commit on S_k-1 judged against its own
    attempt's `paths`; then the kind's artifact rule at Xn. No commit in the whole step (`commit` is B1): only the
    artifact rule, `reused`. Attempt 1 alone is the one-step chain."""
    tip = repo.tree(f"{commit}^{{commit}}")
    if tip is None or tip.sha != commit:  # never a tag, tree or abbreviation that resolves to some other commit
        return Rejected("commit_absent")
    *earlier, last = steps
    chain = [(each.end_commit, each.paths) for each in earlier if each.effect == "commit" and each.end_commit is not None]
    chain += [(commit, last.paths)] if last.effect == "commit" or commit != last.base_commit else []  # a keep over saved work
    if not chain:
        return _artifact(step, tip, rules, reused=True)
    parent = steps[0].base_commit
    relation = repo.relate(parent, commit)
    if relation.ahead != 0:
        return Rejected("not_descendant")
    if relation.behind != len(chain):
        return Rejected("chain_length")
    for sha, paths in chain:
        broken = _link(repo, root, sha, parent, rules, paths)
        if broken is not None:
            return Rejected(broken)
        parent = sha
    return _artifact(step, tip, rules, reused=False)


def _artifact(step: StepKind, tip: Tree, rules: StepRules, *, reused: bool) -> Verdict:
    found = step.artifact(tip, rules)
    return found if isinstance(found, Rejected) else Verified(found, reused)


def _link(repo: Repo, root: Path, sha: str, parent: str, rules: StepRules, paths: tuple[str, ...]) -> Rule | None:
    """One commit of the chain: a commit whose first parent is `parent` (else a merge brought it in), its changes held
    to its own attempt's listed `paths`."""
    tree = repo.tree(f"{sha}^{{commit}}")
    if tree is None or tree.sha != sha:
        return "commit_absent"
    up = repo.tree(f"{sha}^")
    if up is None:
        raise Unreadable("parent")
    if up.sha != parent:
        return "not_descendant"
    return _changes(repo, root, tree, up, rules, paths)


def _changes(repo: Repo, root: Path, tip: Tree, base: Tree, rules: StepRules, paths: tuple[str, ...]) -> Rule | None:
    """One diff B..X: each change added or modified (deletions only when the step allows them), on an allowed path the
    answer listed, mode 100644 at X and, for a change or deletion, at B too (a type change, which the diff reports as a
    change, never turns a symlink, gitlink or executable into a plain file), and every committed blob at most
    `file_cap` bytes after the full read."""
    for change in repo.worktree(root).diff(base.sha, tip.sha, cap=0).changes:
        if (change.kind == "D" and not rules.deletions) or not path_allowed(change.path, rules) or change.path not in paths:
            return "paths"
        if change.kind != "A":
            before = base.files.get(change.path)
            if before is None:
                raise Unreadable("entry")
            if before[0] != MODE:
                return "mode"
        if change.kind == "D":
            continue
        entry = tip.files.get(change.path)
        if entry is None:
            raise Unreadable("entry")
        if entry[0] != MODE:
            return "mode"
        data = tip.read(change.path)
        if data is None:
            raise Unreadable("blob")
        if len(data) > rules.file_cap:
            return "file_size"
    return None
