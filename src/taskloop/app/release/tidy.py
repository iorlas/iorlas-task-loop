"""Leftovers of a branch that has landed: its worktrees and the branch itself. Plain `git worktree remove` only (it refuses a tree with
changes or untracked files, and a locked one), never --force; the branch goes only when patch for patch it is on origin/main."""
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.release.shell import REAL, Shell

BASE = "origin/main"


@dataclass(frozen=True)
class Tree:
    path: Path
    branch: str  # "" when detached


def trees(repo: str | Path, sh: Shell = REAL) -> list[Tree]:
    """Every worktree of the repo (git worktree list), the main checkout first."""
    out = sh.run(["git", "worktree", "list", "--porcelain"], repo, check=False).stdout
    found: list[Tree] = []
    for block in out.split("\n\n"):
        fields: dict[str, str] = {}
        for ln in block.splitlines():
            key, _, val = ln.partition(" ")
            fields[key] = val
        if fields.get("worktree"):
            found.append(Tree(Path(fields["worktree"]), fields.get("branch", "").removeprefix("refs/heads/")))
    return found


def on_base(repo: str | Path, ref: str, sh: Shell = REAL, base: str = BASE) -> bool:
    """True when every commit of `ref` is on `base` by patch (git cherry: a branch replayed by a release is no ancestor but all `-`).
    False when git cannot say."""
    r = sh.run(["git", "cherry", base, ref], repo, check=False)
    return r.returncode == 0 and not any(ln.startswith("+") for ln in r.stdout.splitlines())


def remove_tree(repo: str | Path, path: Path, sh: Shell = REAL) -> str:
    """Remove one worktree; "" when it is gone, else why git kept it."""
    r = sh.run(["git", "worktree", "remove", str(path)], repo, check=False)
    return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git worktree remove failed"])[-1]


def drop_branch(repo: str | Path, branch: str, sh: Shell = REAL) -> list[str]:
    """After a release: the worktrees on `branch` (never the main checkout) and then the local branch. -> one line per thing that
    was kept, with why (empty: all gone). Nothing is forced, so a tree with changes keeps the branch too."""
    if branch in ("main", "master"):
        return []
    main = trees(repo, sh)[:1]
    kept: list[str] = []
    for t in trees(repo, sh):
        if t.branch == branch and t not in main:
            why = remove_tree(repo, t.path, sh)
            if why:
                kept.append(f"worktree {t.path} kept: {why}")
    if kept:
        return [*kept, f"branch {branch} kept: a worktree still has it"]
    if sh.run(["git", "rev-parse", "--verify", "-q", "refs/heads/" + branch], repo, check=False).returncode:
        return []  # no local branch (a remote one was replayed)
    r = sh.run(["git", "branch", "-D", branch], repo, check=False)  # -D: a replayed branch is no ancestor, and on_base was checked
    return [] if r.returncode == 0 else [f"branch {branch} kept: " + (r.stderr.strip().splitlines() or ["git branch -D failed"])[-1]]
